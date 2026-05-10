"""
meshctx LLM驱动记忆提取器 — 使用百炼API进行智能记忆提取
"""
import os
import json
import re
from typing import List, Dict, Any, Optional
from datetime import datetime

# 百炼 API 配置（从 .env 读取，回退到内置key）
BAILIAN_API_KEY = os.environ.get("BAILIAN_API_KEY", "")
BAILIAN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
BAILIAN_MODEL = "qwen-turbo-latest"


class LLMExtractor:
    """基于LLM的智能记忆提取器"""

    def __init__(self, api_key: str = None, model: str = None):
        from openai import OpenAI
        self.client = OpenAI(
            api_key=api_key or BAILIAN_API_KEY,
            base_url=BAILIAN_BASE_URL
        )
        self.model = model or BAILIAN_MODEL

    def extract_memories(self, content: str, role: str = "user",
                         conversation_context: List[Dict] = None) -> List[Dict]:
        """从消息中提取结构化记忆"""
        context_str = ""
        if conversation_context:
            recent = conversation_context[-5:]
            context_str = "\n".join(
                f"[{m.get('role','')}] {m.get('content','')[:200]}"
                for m in recent
            )

        prompt = f"""你是一个记忆提取系统。从以下对话中提取所有值得长期记住的信息。

对话上下文:
{context_str}

最新消息 ({role}):
{content}

请提取所有关键记忆，以JSON数组格式输出，每条记忆包含:
- key: 记忆关键词(简短)
- value: 记忆内容(1-2句话概括)
- importance: 重要性评分(0-1之间的浮点数)
- category: 类别(fact/preference/decision/task/context/other)
- entities: 涉及的人名/项目名/工具名(数组)

只输出JSON数组，不要其他内容。如果没有值得记住的信息，输出空数组 []。"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1000
            )
            result = response.choices[0].message.content.strip()
            # 提取JSON
            return self._parse_json_response(result)
        except Exception as e:
            print(f"[LLMExtractor] 提取失败: {e}")
            return []

    def _parse_json_response(self, text: str) -> List[Dict]:
        """解析LLM返回的JSON"""
        # 尝试直接解析
        try:
            return json.loads(text)
        except:
            pass
        # 尝试提取代码块中的JSON
        m = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except:
                pass
        # 尝试找到第一个[和最后一个]
        start = text.find('[')
        end = text.rfind(']') + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except:
                pass
        return []

    def generate_summary(self, messages: List[Dict]) -> str:
        """为一段对话生成摘要"""
        dialogue = "\n".join(
            f"{m['role']}: {m['content'][:500]}"
            for m in messages[-20:]
        )

        prompt = f"""请用3-5句话总结以下对话的关键内容和结论:

{dialogue}

总结:"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=300
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[LLMExtractor] 摘要生成失败: {e}")
            return ""


# 全局单例
_llm_extractor: Optional[LLMExtractor] = None


def get_llm_extractor() -> LLMExtractor:
    global _llm_extractor
    if _llm_extractor is None:
        _llm_extractor = LLMExtractor()
    return _llm_extractor
