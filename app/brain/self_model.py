from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.learning.self_model import PersistentSelfModel


@dataclass(frozen=True)
class CapabilityReliability:
    capability: str
    tool: str
    attempts: int
    verified: int
    reward: float
    reliability: float
    last_lesson: str = ''

    def to_dict(self) -> dict[str, Any]:
        return {
            'capability': self.capability,
            'tool': self.tool,
            'attempts': self.attempts,
            'verified': self.verified,
            'reward': round(self.reward, 3),
            'reliability': round(self.reliability, 3),
            'last_lesson': self.last_lesson,
        }


class SelfModel:
    """Persistent self-model facade with legacy read compatibility."""

    def __init__(self, registry: dict[str, Any], experiences: Any | None = None):
        self.registry = registry
        self.experiences = experiences
        self._persistent = PersistentSelfModel(experiences) if hasattr(experiences, 'self_model_snapshot') else None

    def reliability(self) -> list[CapabilityReliability]:
        if self._persistent is not None:
            try:
                rows=self._persistent.snapshot(limit=200).get('reliability', [])
                if rows:
                    out=[CapabilityReliability(str(x.get('capability') or x.get('tool')), str(x.get('tool') or ''), int(x.get('attempts') or 0), int(x.get('verified') or 0), float(x.get('reward_mean',0.0) or 0.0), float(x.get('reliability',0.0) or 0.0)) for x in rows if x.get('tool')]
                    out.sort(key=lambda x:(-x.reliability,-x.verified,x.tool))
                    return out
            except Exception:
                pass
        if self.experiences is None:
            return []
        try: rows=self.experiences.by_tool(limit=200)
        except Exception: return []
        grouped:dict[tuple[str,str],list[dict[str,Any]]]={}
        for row in rows:
            grouped.setdefault((str(row.get('capability') or ''),str(row.get('tool') or '')),[]).append(row)
        out=[]
        for (cap,tool),values in grouped.items():
            if not tool: continue
            attempts=len(values); verified=sum(1 for x in values if x.get('verified'))
            rewards=[float(x.get('reward') or 0.0) for x in values]
            out.append(CapabilityReliability(cap,tool,attempts,verified,sum(rewards)/max(1,attempts),verified/max(1,attempts)))
        out.sort(key=lambda x:(-x.reliability,-x.verified,x.tool))
        return out

    def adjustment(self, *, tool: str, capability: str = '', context_signature: str = '') -> float:
        if self._persistent is None:
            return 0.0
        try: return self._persistent.score_adjustment(tool=tool,capability=capability,context_signature=context_signature)
        except Exception: return 0.0

    def snapshot(self) -> dict[str,Any]:
        names=sorted({str(tool.capability or name) for name,tool in self.registry.items()})
        if self._persistent is not None:
            try:
                persistent=self._persistent.snapshot(limit=200)
                if persistent.get('metrics_count',0) or persistent.get('reliability'):
                    return {'version':2,'capabilities':names,'reliability':list(persistent.get('reliability') or []),
                            'known_tools':sorted(self.registry),'limits':list(persistent.get('limits') or []),
                            'metrics_count':int(persistent.get('metrics_count') or 0),'context_metrics':int(persistent.get('context_metrics') or 0)}
            except Exception: pass
        reliability=[x.to_dict() for x in self.reliability()]
        limits=[]
        for item in reliability:
            if item['reliability']<0.5 and item['attempts']>=3:
                limits.append({'tool':item['tool'],'capability':item['capability'],'reason':'low verified reliability from observed runtime history'})
        return {'version':1,'capabilities':names,'reliability':reliability,'known_tools':sorted(self.registry),'limits':limits}

    def describe(self, *, arabic: bool = True) -> str:
        snap=self.snapshot(); reliability=snap.get('reliability') or []; limits=snap.get('limits') or []
        if arabic:
            lines=[f'أعرف حاليًا {len(snap["capabilities"])} capabilities مسجلة.']
            if reliability:
                lines.append('الاعتمادية المقاسة من التجارب:')
                lines.extend(f'• {x["capability"]}/{x["tool"]}: {float(x.get("reliability",0))*100:.0f}% بعد {x["attempts"]} محاولة' for x in reliability[:8])
            if limits:
                lines.append('حدود معروفة:'); lines.extend(f'• {x["tool"]}: {x["reason"]}' for x in limits[:6])
            return '\n'.join(lines)
        lines=[f'I currently know {len(snap["capabilities"])} registered capabilities.']
        if reliability:
            lines.append('Observed reliability from runtime experience:')
            lines.extend(f'• {x["capability"]}/{x["tool"]}: {float(x.get("reliability",0))*100:.0f}% over {x["attempts"]} attempts' for x in reliability[:8])
        if limits:
            lines.append('Known limits:'); lines.extend(f'• {x["tool"]}: {x["reason"]}' for x in limits[:6])
        return '\n'.join(lines)
