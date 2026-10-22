"""动态发布：文案生成、图片生成、发送。"""
import os
import re
import json
import time
import random
import base64
import io
import zipfile
import asyncio
import traceback
import hashlib
import aiohttp
from .network import plugin_http_session
from datetime import datetime, timedelta
from astrbot.api import logger
from .config import (
    DAILY_SUMMARY_FILE, DEFAULT_DYNAMIC_TOPICS, DYNAMIC_LOG_FILE,
    PERMANENT_MEMORY_FILE, TEMP_IMAGE_DIR, WATCH_LOG_FILE, WEEKLY_SUMMARY_FILE,
)
from .runtime import ActionRequest, EventPriority
from .security import wrap_untrusted, redact_outbound
from .content_protocol import (
    ContentProtocolError, DYNAMIC_SCHEMA_PROMPT, parse_dynamic_content,
)


class DynamicMixin:
    """B站动态发布。"""

    async def _queue_dynamic_post(self, text, handler, *, with_outcome=False):
        digest = hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:20]
        date_key = datetime.now().strftime("%Y-%m-%d")
        outcome = await self.event_runtime.execute(
            ActionRequest(
                key=f"post_dynamic:{date_key}:{digest}",
                kind="post_dynamic",
                event_key=f"bilibili:proactive:dynamic:{date_key}",
                target_id=str(self.config.get("DEDE_USER_ID", "") or "self"),
                priority=EventPriority.BACKGROUND,
                metadata={"proactive": True},
            ),
            handler,
        )
        if not outcome.success and str(outcome.reason).startswith("budget_exhausted:"):
            logger.info(f"[BiliBot] 📢 统一行为预算已满，跳过动态：{outcome.reason}")
        elif not outcome.success and outcome.state == "unknown":
            logger.warning("[BiliBot] 动态发布结果未知，不会自动重发")
        return outcome if with_outcome else outcome.success

    def _get_image_gen_config(self):
        backend = str(self.config.get("IMAGE_GEN_BACKEND", "") or "openai").lower().strip()
        if backend in ("novelai", "nai"):
            api_key = self.config.get("IMAGE_GEN_API_KEY", "")
            base_url = str(self.config.get("IMAGE_GEN_API_BASE", "") or "https://image.novelai.net").strip().rstrip("/")
            model = str(self.config.get("IMAGE_GEN_MODEL", "") or "nai-diffusion-4-5-full").strip()
            return "novelai", api_key, base_url, model
        api_key = self.config.get("IMAGE_GEN_API_KEY", "")
        configured_base = str(self.config.get("IMAGE_GEN_API_BASE", "") or "").strip()
        base_url = self._normalize_openai_base_url(configured_base) if configured_base else ""
        model = str(self.config.get("IMAGE_GEN_MODEL", "") or "").strip()
        return "openai", api_key, base_url, model

    @staticmethod
    def _decode_novelai_image(body: bytes, content_type: str) -> bytes:
        """Decode NovelAI's JSON/base64 or ZIP image response."""
        content_type = str(content_type or "").lower()
        if "json" in content_type:
            data = json.loads(body.decode("utf-8"))
            images = data.get("images", []) if isinstance(data, dict) else []
            if not images:
                return b""
            encoded = images[0].get("image", "") if isinstance(images[0], dict) else images[0]
            return base64.b64decode(encoded) if encoded else b""
        if body.startswith(b"PK") or "zip" in content_type:
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                names = [
                    name for name in archive.namelist()
                    if not name.endswith("/") and name.lower().endswith((".png", ".webp", ".jpg", ".jpeg"))
                ]
                return archive.read(names[0]) if names else b""
        if content_type.startswith("image/"):
            return body
        return b""

    async def _generate_novelai_image(self, prompt, api_key, base_url, model):
        if base_url.lower().endswith("/ai/generate-image"):
            url = base_url
        else:
            url = f"{base_url}/ai/generate-image"
        try:
            width = max(64, min(2048, int(self.config.get("IMAGE_GEN_WIDTH", 1024) or 1024)))
            height = max(64, min(2048, int(self.config.get("IMAGE_GEN_HEIGHT", 1024) or 1024)))
            steps = max(1, min(50, int(self.config.get("IMAGE_GEN_STEPS", 28) or 28)))
            scale = max(0.0, min(10.0, float(self.config.get("IMAGE_GEN_SCALE", 5.0) or 5.0)))
        except (TypeError, ValueError):
            width, height, steps, scale = 1024, 1024, 28, 5.0
        negative_prompt = str(
            self.config.get("IMAGE_GEN_NEGATIVE_PROMPT", "")
            or "lowres, blurry, bad anatomy, bad hands, text, watermark"
        ).strip()
        parameters = {
            "params_version": 3,
            "width": width,
            "height": height,
            "scale": scale,
            "sampler": str(self.config.get("IMAGE_GEN_SAMPLER", "") or "k_euler_ancestral"),
            "steps": steps,
            "n_samples": 1,
            "ucPreset": 0,
            "qualityToggle": True,
            "dynamic_thresholding": False,
            "cfg_rescale": 0,
            "noise_schedule": "karras",
            "negative_prompt": negative_prompt,
            "image_format": "png",
        }
        if "diffusion-4" in model:
            parameters.update({
                "v4_prompt": {
                    "caption": {"base_caption": prompt, "char_captions": []},
                    "use_coords": False,
                    "use_order": True,
                },
                "v4_negative_prompt": {
                    "caption": {"base_caption": negative_prompt, "char_captions": []},
                    "legacy_uc": False,
                },
            })
        token = str(api_key).strip()
        auth_value = token if token.lower().startswith("bearer ") else f"Bearer {token}"
        payload = {"input": prompt, "model": model, "action": "generate", "parameters": parameters}
        headers = {
            "Authorization": auth_value,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        async with plugin_http_session(self.config) as s:
            async with s.post(
                url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=180),
            ) as r:
                body = await r.read()
                if r.status not in (200, 201):
                    message = body.decode("utf-8", errors="ignore")
                    logger.error(f"[BiliBot] NovelAI 生图 HTTP {r.status}: {message[:300]}")
                    return None
                img_data = self._decode_novelai_image(body, r.headers.get("Content-Type", ""))
        if not img_data:
            logger.warning("[BiliBot] NovelAI 生图返回中没有可用图片")
            return None
        save_path = os.path.join(TEMP_IMAGE_DIR, f"dynamic_{int(time.time())}.png")
        with open(save_path, "wb") as f:
            f.write(img_data)
        logger.info(f"[BiliBot] 🖼️ NovelAI 图片生成成功（{len(img_data) // 1024}KB）")
        return save_path

    async def _generate_image(self, prompt, human_initiated=False):
        backend, api_key, base_url, model = self._get_image_gen_config()
        if not api_key or not base_url or not model:
            logger.warning("[BiliBot] 图片生成配置不完整，请填写独立密钥、接口地址和模型名称；本次跳过配图")
            return None
        styled_prompt = f"anime style illustration, not photorealistic, soft lighting, beautiful colors: {prompt}"
        if backend == "novelai":
            if not human_initiated:
                logger.warning("[BiliBot] NovelAI 官方要求生图由真人操作触发；本次定时动态跳过配图并降级为纯文字")
                return None
            try:
                return await self._generate_novelai_image(styled_prompt, api_key, base_url, model)
            except Exception as e:
                logger.error(f"[BiliBot] NovelAI 图片生成异常: {e}")
                return None
        url = f"{base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {"model": model, "messages": [{"role": "user", "content": styled_prompt}], "modalities": ["image"]}
        try:
            async with plugin_http_session(self.config) as s:
                async with s.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as r:
                    if r.status != 200:
                        logger.error(f"[BiliBot] 图片生成HTTP错误: {r.status}")
                        return None
                    data = await r.json()
            if "error" in data:
                logger.error(f"[BiliBot] 图片生成API错误: {data['error']}")
                return None
            message = data.get("choices", [{}])[0].get("message", {})
            images = message.get("images", [])
            if images:
                img_item = images[0]
                if isinstance(img_item, dict):
                    img_url = img_item.get("url", "") or img_item.get("b64_json", "") or (img_item.get("image_url", {}) or {}).get("url", "")
                else:
                    img_url = str(img_item)
                if img_url.startswith("data:image"):
                    img_b64 = img_url.split(",", 1)[1]
                    img_data = base64.b64decode(img_b64)
                    save_path = os.path.join(TEMP_IMAGE_DIR, f"dynamic_{int(time.time())}.png")
                    with open(save_path, "wb") as f:
                        f.write(img_data)
                    logger.info(f"[BiliBot] 🖼️ 图片生成成功（{len(img_data) // 1024}KB）")
                    return save_path
            content = message.get("content", "")
            if isinstance(content, str) and "data:image" in content:
                match = re.search(r'data:image/\w+;base64,([A-Za-z0-9+/=]+)', content)
                if match:
                    img_data = base64.b64decode(match.group(1))
                    save_path = os.path.join(TEMP_IMAGE_DIR, f"dynamic_{int(time.time())}.png")
                    with open(save_path, "wb") as f:
                        f.write(img_data)
                    logger.info(f"[BiliBot] 🖼️ 图片生成成功（{len(img_data) // 1024}KB）")
                    return save_path
            logger.warning("[BiliBot] 图片生成返回无图片")
            return None
        except Exception as e:
            logger.error(f"[BiliBot] 图片生成异常: {e}")
            return None

    def _dynamic_post_due(self, history=None):
        history = history if isinstance(history, list) else self._load_json(DYNAMIC_LOG_FILE, [])
        try:
            days = max(1, min(30, int(self.config.get("DYNAMIC_MIN_INTERVAL_DAYS", 1))))
        except (TypeError, ValueError):
            days = 1
        today = datetime.now().date()
        for item in reversed(history):
            if not isinstance(item, dict):
                continue
            # 周报/日报是固定投递，不占用普通动态的最短间隔。
            if item.get("weekly") or item.get("daily_summary"):
                continue
            try:
                posted = datetime.strptime(str(item.get("time", ""))[:10], "%Y-%m-%d").date()
            except ValueError:
                continue
            elapsed = (today - posted).days
            # 未来日期（改时区或手改日志）不能让动态永久停摆。
            if 0 <= elapsed < days:
                return False
        return True

    def _dynamic_grounding_context(self):
        """Public self-experiences can motivate a post even without an 8/10 video."""
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M")
        reasons = []
        watched = self._load_json(WATCH_LOG_FILE, [])
        for item in reversed(watched if isinstance(watched, list) else []):
            if not isinstance(item, dict) or str(item.get("time", "")) < cutoff:
                continue
            title = str(item.get("title", ""))[:60]
            review = str(item.get("review") or item.get("comment") or "").strip()[:160]
            if title and review and review not in {"评价失败", "没什么感觉", "未知"} and item.get("analysis_basis") != "metadata":
                reasons.append(f"[{str(item.get('time', ''))[:10]}] 视频《{title}》：{review}；内容：{str(item.get('content_summary', ''))[:180]}")
            if len(reasons) >= 4:
                break
        # Only public self memories; private conversations and owner profiles never become post material.
        for item in reversed(getattr(self, "_memory", [])):
            if not isinstance(item, dict) or item.get("user_id") != "self":
                continue
            if item.get("memory_type") not in {"video", "bangumi", "dynamic"}:
                continue
            if str(item.get("source", "")).lower() in {"qq", "private", "private_message", "bilibili_private"} or item.get("privacy"):
                continue
            if str(item.get("time", "")) < cutoff:
                continue
            # 动态记忆的 rpid 是 dynamic_<ts>，thread_id 才是 "dynamic"；
            # 只比较 rpid == "dynamic" 会让刚发过的动态重新变成素材。
            if (str(item.get("thread_id") or "").strip() == "dynamic"
                    or str(item.get("rpid") or "").startswith("dynamic_")):
                continue
            text = str(item.get("text") or "").strip()[:220]
            if text:
                reasons.append(f"近期公开活动记忆（日期 {str(item.get('time', ''))[:10]}）：{text}")
            if len(reasons) >= 6:
                break
        # Only structured public media highlights from archived diaries, never raw chat summaries.
        for filename in (DAILY_SUMMARY_FILE, WEEKLY_SUMMARY_FILE):
            records = self._load_json(filename, [])
            for record in reversed(records if isinstance(records, list) else []):
                if not isinstance(record, dict) or str(record.get("date") or record.get("time") or "")[:10] < cutoff[:10]:
                    continue
                structured = record.get("structured", {})
                if not isinstance(structured, dict):
                    continue
                for key in ("video_highlights", "bangumi_highlights"):
                    highlights = structured.get(key, [])
                    for item in highlights[:2] if isinstance(highlights, list) else []:
                        if isinstance(item, dict) and item.get("title"):
                            reasons.append(f"近期观看回顾：{str(item.get('title'))[:60]}；{str(item.get('review') or item.get('summary') or '')[:120]}")
                break
        return [redact_outbound(re.sub(r"\s+", " ", item), internal=False)[0] for item in reasons[:6]]

    async def _generate_dynamic_content(self, human_initiated=False):
        perm = self._load_json(PERMANENT_MEMORY_FILE, [])
        perm_section = ""
        if perm:
            perm_section = "\n【你的自我认知】\n" + "\n".join([p["text"] for p in perm[-20:]])
        history_log = self._load_json(DYNAMIC_LOG_FILE, [])
        history_section = ""
        if history_log:
            recent_dynamics = [h.get("text", "") for h in history_log[-10:] if h.get("text")]
            if recent_dynamics:
                history_section = "\n【最近发过的动态（不要重复类似内容）】\n" + "\n".join([f"- {d[:50]}..." if len(d) > 50 else f"- {d}" for d in recent_dynamics])
        now = datetime.now()
        hour = now.hour
        if hour < 6:
            time_hint = "现在是深夜/凌晨"
        elif hour < 12:
            time_hint = "现在是上午"
        elif hour < 18:
            time_hint = "现在是下午"
        else:
            time_hint = "现在是晚上"
        custom_topics = self.config.get("DYNAMIC_TOPICS", [])
        topics = custom_topics if custom_topics and isinstance(custom_topics, list) else DEFAULT_DYNAMIC_TOPICS
        if not topics:
            topics = ["只在今天确实有具体事情想说时，挑一个片段随口记下"]
        topic = random.choice(topics)
        sp = await self._get_system_prompt()
        mood, mood_reason = self._get_today_mood() if hasattr(self, "_get_today_mood") else ("平静", "")
        grounding = self._dynamic_grounding_context()
        grounding_text = wrap_untrusted("\n".join(f"- {item}" for item in grounding) or "近期没有足够具体的活动素材", "public_activity_memory")
        prompt = f"""你准备判断现在是否值得发一条B站动态。当前时段是：{time_hint}。管理员给的方向：{topic}{perm_section}{history_section}

当前心情：{mood}（{str(mood_reason)[:120]}）。心情可以影响表达，但不能据此编造经历。
近期可以作为依据的真实片段（按原日期叙述，过去的事不能说成今天）：
{grounding_text}
触发方式：{'管理员刚刚手动要求发动态' if human_initiated else '后台定时时刻到达'}

B站动态的感觉：
- 结合你的人设、近期公开观看记忆和当前心情，选择一个真实具体的细节写感想、吐槽、问题或联想；普通视频、困惑和不喜欢的体验也可以表达，不需要8分以上或强烈情绪。若确有新角度就选择post；定时到达表示一次表达机会；定时时刻本身不是发布理由，也不是必须完成的数量
- 已有具体素材时主动尝试组织一条自然表达，不因为“没有惊艳发现”就跳过；没有具体素材或只会重复旧内容才选择skip。不能编造外出、游戏实操或线下生活经历，也不能公开私信、QQ聊天或主人的私密画像
- 管理员手动触发时可以围绕给定方向创作，但仍不能伪造经历
- 像本人忽然想起一个具体小事、感受或吐槽后随手发出来，不像在完成“发动态”任务
- 一条只说一个中心，先让读者看得懂发生了什么或你在想什么；不要故作深沉、写成谜语或强行升华
- 当前时段只是背景，确实和内容有关时再自然带到；不要为了“真实感”凭空声称自己在摸鱼、追番、出门或经历了某件事
- 不写运营口吻、鸡汤结尾、每日打卡式开场，也不要习惯性向大家提问或讨互动
- 句式和长短可以变化，通常1到2句、15到80字；没有足够内容时宁可短，不凑到固定篇幅
- 不要和最近发过的动态内容重复或相似

注意：默认不配图；只有内容里确实有一个适合呈现的具体画面、且图片能补充文字时才将need_image设为true。
{DYNAMIC_SCHEMA_PROMPT}"""
        custom_dynamic_inst = self.config.get("CUSTOM_DYNAMIC_INSTRUCTION", "")
        if custom_dynamic_inst:
            prompt += f"\n\n【补充提示词】{custom_dynamic_inst}"
        try:
            text = await getattr(self, "_generation_llm_call", self._llm_call)(prompt, system_prompt=sp, max_tokens=500)
            if not text:
                return None
            try:
                return parse_dynamic_content(text)
            except ContentProtocolError as exc:
                logger.warning(f"[BiliBot] 动态内容结构校验失败，本次不发: {exc}")
                return None
        except Exception as e:
            logger.error(f"[BiliBot] 生成动态内容失败: {e}")
            return None

    async def _run_dynamic(self, human_initiated=False):
        lock = getattr(self, "_dynamic_run_lock", None)
        if lock is None:
            lock = self._dynamic_run_lock = asyncio.Lock()
        if lock.locked():
            logger.info("[BiliBot] 📢 已有动态发布流程在进行，本次跳过")
            return False
        async with lock:
            try:
                await self._run_dynamic_inner(human_initiated=human_initiated)
            except asyncio.CancelledError:
                logger.info("[BiliBot] 动态发布任务被取消")
            except Exception as e:
                logger.error(f"[BiliBot] 动态发布任务异常退出: {e}\n{traceback.format_exc()}")
        return True

    async def _run_dynamic_inner(self, human_initiated=False):
        logger.info("[BiliBot] 📢 开始发布动态...")
        log = self._load_json(DYNAMIC_LOG_FILE, [])
        today = datetime.now().strftime("%Y-%m-%d")
        # 与 _dynamic_post_due 口径一致：周报/日报是固定投递，既不占最短间隔，也不占每日条数。
        today_posts = [item for item in log if isinstance(item, dict)
                       and str(item.get("time", "")).startswith(today)
                       and not item.get("weekly") and not item.get("daily_summary")]

        def _limit(key, default):
            try:
                return max(0, int(self.config.get(key, default) or 0))
            except (TypeError, ValueError):
                return max(0, int(default))

        # 0 与空值表示该项不设限，与 behavior_budget 的规则保持一致；
        # 真正的硬上限由其他非零项和统一行为预算共同约束。
        limits = [
            value for value in (
                _limit("DYNAMIC_DAILY_COUNT", 1),
                self._autonomous_limit_max("dynamic") if hasattr(self, "_autonomous_limit_max") else _limit("AUTONOMOUS_DYNAMIC_DAILY_LIMIT", 2),
            ) if value > 0
        ]
        plan = self._autonomous_plan_for_today() if hasattr(self, "_autonomous_plan_for_today") else {}
        if plan and not human_initiated:
            plan_limit = len(plan.get("dynamic_times", []))
            if plan_limit:
                limits.append(plan_limit)
        if limits and len(today_posts) >= min(limits):
            logger.info(f"[BiliBot] 今天已发 {len(today_posts)} 条动态（上限 {min(limits)}），跳过")
            return
        if not human_initiated and not self._dynamic_post_due(log):
            logger.info("[BiliBot] 尚未到自动动态发布间隔，跳过")
            return
        logger.info("[BiliBot] 🤔 正在想要发什么...")
        content = await self._generate_dynamic_content(human_initiated=human_initiated)
        if not content:
            logger.error("[BiliBot] ❌ 生成动态内容失败")
            return
        if content.get("decision") != "post":
            logger.info("[BiliBot] 今天没有足够具体的动态发布动机，本次跳过")
            return
        text = str(content.get("text", "") or "").strip()
        if not text:
            logger.warning("[BiliBot] 动态文案为空，跳过本次发布")
            return
        need_image = content.get("need_image", False)
        image_prompt = content.get("image_prompt", "")
        logger.info(f"[BiliBot] 📝 文案：{text[:50]}...")
        logger.info(f"[BiliBot] 🖼️ 需要图片：{need_image}")
        success = False
        image_sent = False
        if need_image and image_prompt:
            logger.info(f"[BiliBot] 🎨 生图提示：{image_prompt[:50]}...")
            local_path = await self._generate_image(image_prompt, human_initiated=human_initiated)
            if local_path:
                img_info = await self._upload_image_to_bilibili(local_path)
                if img_info:
                    # 带图接口失败时会在内部降级为纯文字，这里记录真实结果。
                    image_state = {"sent": False}
                    outcome = await self._queue_dynamic_post(
                        text,
                        lambda: self._post_dynamic_with_image(text, img_info, image_state),
                        with_outcome=True,
                    )
                    success = outcome.success
                    image_sent = bool(outcome.success and image_state.get("sent"))
                else:
                    success = await self._queue_dynamic_post(
                        text, lambda: self._post_dynamic_text(text)
                    )
                try:
                    os.remove(local_path)
                except Exception:
                    pass
            else:
                success = await self._queue_dynamic_post(
                    text, lambda: self._post_dynamic_text(text)
                )
        else:
            success = await self._queue_dynamic_post(
                text, lambda: self._post_dynamic_text(text)
            )
        if success:
            log.append({"time": datetime.now().strftime("%Y-%m-%d %H:%M"), "text": text,
                        "has_image": image_sent, "image_prompt": image_prompt if image_sent else ""})
            self._save_json(DYNAMIC_LOG_FILE, log[-100:])
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            short_text = text[:60] if len(text) > 60 else text
            await self._save_self_memory_record("dynamic", f"[{now_str}] Bot发了一条动态：{short_text}", source="bilibili", memory_type="dynamic")
            logger.info("[BiliBot] 🎉 动态发布完成！")
        else:
            logger.error("[BiliBot] ❌ 动态发布失败")
