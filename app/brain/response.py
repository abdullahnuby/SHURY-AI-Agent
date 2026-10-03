from __future__ import annotations

import re
from typing import Any

from app.brain.models import CognitiveState, Decision


def _ar(state: CognitiveState) -> bool:
    return bool(state.semantic and state.semantic.language in {'ar', 'mixed'})


def _evidence_answer(state: CognitiveState, *, arabic: bool) -> str:
    if not state.evidence:
        return 'مش عندي دليل كفاية للإجابة، ومش هخمن.' if arabic else "I don't have enough evidence to answer that, so I won't guess."
    evidence = state.evidence[:8]
    if state.semantic and state.semantic.question_type == 'memory_profile':
        rows = []
        for item in evidence:
            content = item.content.strip()
            if not content:
                continue
            if '=' in content:
                key, value = content.split('=', 1)
                rows.append(f'• {key.strip()}: {value.strip()}')
            else:
                rows.append(f'• {content}')
        if rows:
            return ('المعلومات المحفوظة عندي:\n' if arabic else 'Stored information I have:\n') + '\n'.join(rows)
    first = evidence[0]
    if first.kind in {'belief', 'memory', 'legacy_memory'}:
        content = first.content.strip()
        if '=' in content:
            key, value = content.split('=', 1)
            value = value.strip()
            return (f'حسب المعلومة المحفوظة عندي: {value}.' if arabic else f'According to my stored information: {value}.')
    prefix = 'لقيت الدليل ده:' if arabic else 'I found this evidence:'
    return prefix + '\n' + '\n'.join(f'• {x.content}' for x in evidence)


def _self_model_answer(state: CognitiveState, *, arabic: bool) -> str:
    snap = state.self_model or {}
    caps = snap.get('capabilities') or []
    reliability = snap.get('reliability') or []
    limits = snap.get('limits') or []
    if arabic:
        lines = [f'أعرف حاليًا {len(caps)} قدرات مسجلة.']
        if reliability:
            lines.append('وأقيس اعتماديتي من التجارب الفعلية، مثلًا:')
            lines.extend(f'• {x["capability"]}: {x["reliability"] * 100:.0f}% في {x["attempts"]} محاولة' for x in reliability[:6])
        if limits:
            lines.append('ولدي حدود مسجلة من التجربة:')
            lines.extend(f'• {x["capability"]}: اعتمادية منخفضة حاليًا' for x in limits[:5])
        return '\n'.join(lines)
    lines = [f'I currently have {len(caps)} registered capabilities.']
    if reliability:
        lines.append('I measure reliability from observed runtime experience:')
        lines.extend(f'• {x["capability"]}: {x["reliability"] * 100:.0f}% over {x["attempts"]} attempts' for x in reliability[:6])
    if limits:
        lines.append('Known observed limits:')
        lines.extend(f'• {x["capability"]}: currently low reliability' for x in limits[:5])
    return '\n'.join(lines)


def _clean_internal(text: str) -> str:
    text = str(text or '').strip()
    if not text:
        return ''
    if text.startswith('{') and text.endswith('}'):
        # Internal envelopes must never become user-facing prose.
        return ''
    if '"task_id"' in text or '"session_id"' in text:
        return ''
    return text


def compose(decision: Decision, state: CognitiveState) -> str:
    arabic = _ar(state)
    if decision.kind == 'respond':
        if decision.answer_source == 'conversation':
            return 'أهلًا بيك. أنا شوري.' if arabic else "Hello. I'm SHURY."
        if decision.answer_source == 'self_model':
            return _self_model_answer(state, arabic=arabic)
        if decision.answer_source in {'beliefs', 'memory'}:
            return _evidence_answer(state, arabic=arabic)
        if decision.evidence:
            return _evidence_answer(state, arabic=arabic)
    if decision.kind == 'retrieve':
        return 'هراجع الذاكرة المحفوظة وأبني الرد على الدليل.' if arabic else 'I will check durable memory and ground the answer in evidence.'
    if decision.kind == 'research':
        if decision.answer_source == 'open_world_learning':
            return 'هتعلم الموضوع من مصادر مستقلة، أقارن الأدلة، وأحتفظ بالمعرفة القابلة لإعادة الاستخدام.' if arabic else 'I will investigate the topic from independent sources, compare the evidence, and retain reusable knowledge.'
        return 'هجيب evidence موثوق قبل ما أجاوب.' if arabic else 'I need grounded evidence before I answer.'
    if decision.kind == 'execute':
        return 'هحوّل الهدف لخطة تنفيذ وأتحقق من النتيجة.' if arabic else 'I will execute the planned actions and verify the result.'
    if decision.kind == 'clarify':
        missing = '، '.join(x for x in decision.missing_information if x)
        if 'learning_topic' in decision.missing_information:
            return (
                'عايزني أتعلم إيه تحديدًا؟ مثال: أحدث أبحاث RAG والوكلاء الذكية.'
                if arabic else
                'What should I learn specifically? For example: the latest research on RAG and intelligent agents.'
            )
        return (f'محتاج تحديد: {missing}' if missing else 'محتاج معلومة إضافية تحدد الهدف.') if arabic else (f'I need: {missing}' if missing else 'I need one more detail to determine the goal.')
    if decision.kind == 'refuse':
        return 'مش هقدر أنفذ العملية دي ضمن الحدود الحالية.' if arabic else 'I cannot execute that within my current boundaries.'
    return 'مش هخمن في حاجة معنديش عليها دليل.' if arabic else "I won't guess without evidence."


def compose_action_result(state: CognitiveState, *, action: Any, output: Any, all_outputs: dict[str, Any]) -> str:
    """Render an observed result from semantics + result shape, not per-tool templates."""
    arabic = _ar(state)
    clean = _clean_internal(str(output)) if output is not None else ''
    operation = state.semantic.requested_operation if state.semantic else ''

    if operation == 'query_identity':
        return (f'اسمك {clean}.' if arabic else f'Your name is {clean}.') if clean else ('مش لاقي اسم محفوظ.' if arabic else "I don't have a stored name.")
    if operation == 'query_memory' and clean:
        key = state.semantic.slot('key') if state.semantic else ''
        labels_ar = {'city': 'مدينتك', 'origin': 'بلد/مدينة أصلك', 'language': 'لغتك'}
        labels_en = {'city': 'your city', 'origin': 'your origin', 'language': 'your language'}
        label = (labels_ar if arabic else labels_en).get(key, key or 'المعلومة المحفوظة' if arabic else 'stored information')
        return f'{label}: {clean}.' if arabic else f'{label}: {clean}.'
    if operation == 'query_time':
        return (f'الوقت الحالي هو {clean}.' if arabic else f'The current time is {clean}.') if clean else ('ملقتش وقت صالح في النتيجة.' if arabic else 'No valid time was returned.')
    if operation == 'calculate':
        return (f'النتيجة = {clean}.' if arabic else f'The result is {clean}.') if clean else ('الحساب لم يُرجع نتيجة.' if arabic else 'The calculation returned no result.')
    if operation == 'remember':
        predicate = state.semantic.slot('predicate') if state.semantic else ''
        value = state.semantic.slot('value') if state.semantic else ''
        if arabic and predicate == 'name' and value:
            return f'تشرفت يا {value}.'
        if arabic and predicate in {'origin', 'city'} and value:
            return f'تمام، هفتكر إنك من {value}.'
        if arabic and predicate and value:
            return f'تمام، هفتكر إن {predicate} = {value}.'
        return 'تم حفظ المعلومة.' if arabic else 'The information was saved.'
    if operation == 'compound_calculate_remember':
        value = all_outputs.get('s1')
        key = state.semantic.slot('result_key') if state.semantic else 'total'
        value_text = str(value) if value is not None else ''
        return (f'حسبتها = {value_text}، وحفظتها باسم {key}.' if arabic else f'I calculated {value_text} and saved it as {key}.')
    if operation in {'research', 'learning_intent'} and isinstance(output, dict) and ('evidence_count' in output or 'new_evidence_count' in output):
        query = str(
            output.get('query')
            or (state.semantic.slot('query') if state.semantic and state.semantic.slot('query') else '')
            or (state.semantic.slot('learning_topic') if state.semantic else '')
            or ''
        ).strip()
        evidence_count = int(output.get('evidence_count') or 0)
        new_count = int(output.get('new_evidence_count') or 0)
        route = output.get('route') or []
        lines: list[str] = []
        exploration_events = [e for e in state.trace if e.get('kind') == 'exploration_decision']
        explored_first = bool(exploration_events and any(e.get('mode') == 'information' for e in exploration_events))
        if explored_first:
            lines.append(
                'بدأت بمراجعة المعلومات المتاحة ثم انتقلت للمصدر الخارجي عند الحاجة.'
                if arabic else
                'I first checked available evidence, then moved to external sources when needed.'
            )
        lines.append(('تم البحث والتعلم عن: ' + query) if arabic else ('Researched and learned about: ' + query))
        lines.append((f'الأدلة: {evidence_count}، الجديدة: {new_count}.') if arabic else (f'Evidence: {evidence_count}; new evidence: {new_count}.'))
        if route:
            providers = [str(x.get('source')) for x in route if isinstance(x, dict) and x.get('source')]
            if providers:
                lines.append(('المصادر: ' + ' → '.join(providers)) if arabic else ('Sources: ' + ' → '.join(providers)))
        evidence = output.get('evidence') or []
        titles = []
        for item in evidence[:4]:
            if not isinstance(item, dict): continue
            title = str(item.get('title') or '').strip()
            url = str(item.get('url') or '').strip()
            if title: titles.append(f'• {title}' + (f' — {url}' if url else ''))
        if titles:
            lines.append(('أهم الأدلة:' if arabic else 'Key evidence:'))
            lines.extend(titles)
        if output.get('candidate_skill'):
            lines.append('حوّلت المعرفة إلى candidate declarative skill؛ مش هتتحول لسلوك تنفيذي تلقائي.' if arabic else 'I converted the result into a declarative skill candidate; it is not executable automatically.')
        return '\n'.join(lines)

    if isinstance(output, dict) and output.get('answer'):
        answer = _clean_internal(str(output['answer']))
        evidence = output.get('evidence') or []
        if evidence:
            refs = []
            for item in evidence[:4]:
                if isinstance(item, dict):
                    title = str(item.get('title') or item.get('source') or '').strip()
                    url = str(item.get('url') or '').strip()
                    if title and url:
                        refs.append(f'• {title} — {url}')
                    elif title:
                        refs.append(f'• {title}')
                    elif url:
                        refs.append(f'• {url}')
            if refs:
                answer += ('\n\nالمصادر:\n' if arabic else '\n\nSources:\n') + '\n'.join(refs)
        return answer
    if isinstance(output, list):
        items = []
        for item in output[:8]:
            if isinstance(item, dict):
                label = item.get('name') or item.get('key') or item.get('value') or item.get('summary')
                if label:
                    items.append(str(label))
            elif item is not None:
                items.append(str(item))
        if items:
            return ('النتيجة:\n' if arabic else 'Result:\n') + '\n'.join(f'• {x}' for x in items)
    if clean:
        return clean
    return compose(state.decision or Decision('respond', 0, ''), state)
