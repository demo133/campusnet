"""Provider 注册表与指纹识别。"""

from __future__ import annotations

from typing import Dict, List, Tuple, Type

from .base import DetectContext, LoginResult, Provider
from .custom import CustomProvider
from .drcom import DrComProvider
from .eportal import EportalProvider
from .ruijie import RuijieProvider
from .srun import SrunProvider

#: 注册顺序决定了同分时的优先级
PROVIDERS: Dict[str, Type[Provider]] = {
    p.name: p for p in (DrComProvider, SrunProvider, RuijieProvider, EportalProvider, CustomProvider)
}

__all__ = [
    "PROVIDERS",
    "Provider",
    "DetectContext",
    "LoginResult",
    "DrComProvider",
    "SrunProvider",
    "RuijieProvider",
    "EportalProvider",
    "CustomProvider",
    "get_provider",
    "fingerprint",
    "rank",
]


def get_provider(name: str) -> Type[Provider]:
    key = (name or "").strip().lower()
    if key in PROVIDERS:
        return PROVIDERS[key]
    raise KeyError("未知的 provider：{!r}（可选：{}）".format(name, ", ".join(PROVIDERS)))


def fingerprint(ctx: DetectContext) -> List[Tuple[str, float]]:
    """给一个门户页面打分，返回 ``[(provider, 置信度)]``，按分数降序。"""
    scored = []
    for name, cls in PROVIDERS.items():
        try:
            score = float(cls.detect(ctx))
        except Exception:  # noqa: BLE001 - 单个 provider 的 bug 不该拖垮识别
            score = 0.0
        if score >= cls.min_confidence:
            scored.append((name, round(score, 3)))
    scored.sort(key=lambda item: (-item[1], list(PROVIDERS).index(item[0])))
    return scored


def rank(ctx: DetectContext, limit: int = 3) -> List[str]:
    """按置信度给出要依次尝试的 provider 名字。"""
    names = [name for name, _ in fingerprint(ctx)]
    if not names:
        # 全都没认出来 —— 给一个保守的兜底顺序
        names = ["drcom", "eportal", "srun", "ruijie"]
    return names[:limit]
