import json
import os
import re
from datetime import datetime
from pathlib import Path

import streamlit as st
from openai import OpenAI

APP_DIR = Path(__file__).parent
DATA_FILE = APP_DIR / "project.json"

DEFAULT_DATA = {
    "meta": {
        "title": "새 드라마",
        "genre": "막장 가족극 / 미스터리",
        "format": "숏폼 10부작, 회당 60~120초",
        "tone": "빠르고 자극적이되, 인물의 행동에는 분명한 이유가 있다.",
        "premise": "",
        "final_truth": "",
        "episode_count": 10,
    },
    "characters": [],
    "relationships": [],
    "timeline": [],
    "foreshadowing": [],
    "season_plan": [],
    "knowledge": [],
    "episodes": [],
    "notes": [],
    "creative_controls": {"makjang": 8, "twist": 8, "realism": 7, "legal_accuracy": 6},
    "writer_rules": [
        {"id":"RULE-001","text":"현실의 법률·제도가 핵심 장치라면 확정 전에 실제 성립 가능성을 검증한다."},
        {"id":"RULE-002","text":"장기간 유지된 비밀에는 발견되지 않은 구체적인 이유가 있어야 한다."},
        {"id":"RULE-003","text":"재산·상속을 둘러싼 욕망은 실제 법적 권리와 인물이 권리가 있다고 믿는 이유를 구분한다."},
        {"id":"RULE-004","text":"반전을 위해 정상적인 인물이 당연히 할 질문을 하지 않게 만들지 않는다."},
        {"id":"RULE-005","text":"문제 하나를 수정할 때 관련 없는 확정 설정까지 연쇄적으로 바꾸지 않는다."},
        {"id":"RULE-006","text":"AI가 새로 제안한 설정은 사용자 승인 전까지 Canon이 아니다."},
        {"id":"RULE-007","text":"검증 과정이 장르의 핵심 재미를 제거하거나 법률·절차 설명을 이야기의 중심으로 만들지 않는다."}
    ],
    "concept_lab": {
        "brief":"",
        "candidate":"",
        "audit":"",
        "audit_digest":{},
        "revised":"",
        "revision_note":"",
        "revision_approved":False,
        "reaudit":"",
        "refine_note":"",
        "refine_round":0,
        "refine_history":[],
        "external_checks":[],
        "conditional_canon":False,
        "locked":False,
        "raw_locked_candidate":"",
        "canon_master":"",
        "canon_refined_at":"",
        "locked_bible":"",
        "locked_at":""
    },
    "season_locked": False,
    "season_audit": "",
    "season_repair_round": 0,
    "season_repair_history": [],
    "season_repair_engine_version": "2.8.3",
    "season_repair_resolved": []
}


def clone_default():
    return json.loads(json.dumps(DEFAULT_DATA, ensure_ascii=False))


def migrate_data(raw):
    """1.x 프로젝트 JSON도 2.0에서 그대로 열리도록 누락 필드를 보충한다."""
    base = clone_default()
    if not isinstance(raw, dict):
        return base
    for key in base:
        if key in raw:
            base[key] = raw[key]
    if not isinstance(base.get("meta"), dict):
        base["meta"] = clone_default()["meta"]
    for k, v in clone_default()["meta"].items():
        base["meta"].setdefault(k, v)
    for key in ["characters", "relationships", "timeline", "foreshadowing",
                "season_plan", "knowledge", "episodes", "notes", "writer_rules"]:
        if not isinstance(base.get(key), list):
            base[key] = []
    if not isinstance(base.get("creative_controls"), dict):
        base["creative_controls"] = clone_default()["creative_controls"]
    for k, v in clone_default()["creative_controls"].items():
        base["creative_controls"].setdefault(k, v)
    if not isinstance(base.get("concept_lab"), dict):
        base["concept_lab"] = clone_default()["concept_lab"]
    for k, v in clone_default()["concept_lab"].items():
        base["concept_lab"].setdefault(k, v)
    if not isinstance(base.get("season_locked"), bool):
        base["season_locked"] = False
    base.setdefault("season_audit", "")
    if not isinstance(base.get("season_repair_round"), int):
        base["season_repair_round"] = 0
    if not isinstance(base.get("season_repair_history"), list):
        base["season_repair_history"] = []
    if not isinstance(base.get("season_repair_resolved"), list):
        base["season_repair_resolved"] = []
    # 2.8.3: 보완 엔진이 바뀌면 횟수만 새 세션으로 초기화한다. 과거 이력은 보존한다.
    if base.get("season_repair_engine_version") != "2.8.3":
        base["season_repair_round"] = 0
        base["season_repair_resolved"] = []
        base.pop("season_last_repair_rejection", None)
        base["season_repair_engine_version"] = "2.8.3"
    return base


def load_data():
    if DATA_FILE.exists():
        try:
            return migrate_data(json.loads(DATA_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return clone_default()


def save_data(data):
    DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def slugify(text):
    text = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", str(text).strip())
    return text[:80] or "project"


def get_client(api_key):
    return OpenAI(api_key=api_key)


def call_model(api_key, model, instructions, prompt):
    client = get_client(api_key)
    resp = client.responses.create(
        model=model,
        instructions=instructions,
        input=prompt,
    )
    return resp.output_text.strip()


def extract_json(text):
    """AI 응답에서 JSON 배열/객체를 최대한 안전하게 꺼낸다."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    for opener, closer in [("[", "]"), ("{", "}")]:
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except Exception:
                pass
    raise ValueError("AI 응답에서 JSON을 읽지 못했습니다.")


def season_plan_text(data):
    plans = sorted(data.get("season_plan", []), key=lambda x: x.get("number", 0))
    if not plans:
        return "아직 전체 시즌 설계가 없습니다."
    return json.dumps(plans, ensure_ascii=False, indent=2)


def compact_context(data, current_episode=None, last_episode_count=4):
    meta = data["meta"]
    recent = sorted(data["episodes"], key=lambda x: x.get("number", 0))[-last_episode_count:]
    target_plan = None
    if current_episode is not None:
        target_plan = next(
            (p for p in data["season_plan"] if p.get("number") == int(current_episode)),
            None
        )

    return f"""# 작가실 영구 규칙
{json.dumps(data.get('writer_rules', []), ensure_ascii=False, indent=2)}

# 작품 성향
{creative_controls_text(data)}

# 잠금된 기획 바이블
{data.get('concept_lab', {}).get('locked_bible', '') or "아직 잠금된 기획 없음"}

# 외부 확인이 필요한 미검증 전문 사실
{json.dumps(data.get('concept_lab', {}).get('external_checks', []), ensure_ascii=False, indent=2)}
주의: 위 항목은 Canon의 확정 전문 사실이 아니다. 확인 전에는 법률/제도 결론을 단정하거나 핵심 사건 해결 근거로 사용하지 말 것.

# 작품 바이블
제목: {meta.get('title','')}
장르: {meta.get('genre','')}
형식: {meta.get('format','')}
톤/문체: {meta.get('tone','')}
기본 설정/로그라인: {meta.get('premise','')}
작가만 아는 최종 진실: {meta.get('final_truth','')}
총 회차: {meta.get('episode_count',10)}

# 인물
{json.dumps(data['characters'], ensure_ascii=False, indent=2)}

# 관계
{json.dumps(data['relationships'], ensure_ascii=False, indent=2)}

# 사건 연표
{json.dumps(data['timeline'], ensure_ascii=False, indent=2)}

# 떡밥 장부
{json.dumps(data['foreshadowing'], ensure_ascii=False, indent=2)}

# 인물별 정보 보유 장부
{json.dumps(data['knowledge'], ensure_ascii=False, indent=2)}

# 전체 시즌 설계
{season_plan_text(data)}

# 이번 회차의 고정 설계
{json.dumps(target_plan, ensure_ascii=False, indent=2) if target_plan else "없음"}

# 최근 완성 회차
{json.dumps(recent, ensure_ascii=False, indent=2)}
"""


def deterministic_audit(data):
    issues = []
    chars = {
        c.get("name", "").strip(): c
        for c in data["characters"]
        if c.get("name", "").strip()
    }

    for name, c in chars.items():
        age = c.get("age")
        for field, label in [("biological_mother", "친모"), ("biological_father", "친부")]:
            p = str(c.get(field, "")).strip()
            if not p:
                continue
            if p == name:
                issues.append(f"❌ {name}: 자기 자신이 {label}로 설정되어 있습니다.")
            elif p not in chars:
                issues.append(f"⚠️ {name}: {label} '{p}'가 인물 목록에 없습니다.")
            else:
                pa = chars[p].get("age")
                if isinstance(age, int) and isinstance(pa, int) and pa - age < 13:
                    issues.append(
                        f"❌ {name}({age})와 {label} {p}({pa})의 나이 차가 {pa-age}세뿐입니다."
                    )

    def parents(name):
        if name not in chars:
            return set()
        c = chars[name]
        return {
            x for x in [
                str(c.get("biological_mother", "")).strip(),
                str(c.get("biological_father", "")).strip()
            ] if x
        }

    def ancestors(name, depth=5):
        seen, frontier = set(), {name}
        for _ in range(depth):
            nxt = set()
            for node in frontier:
                for p in parents(node):
                    if p not in seen:
                        seen.add(p)
                        nxt.add(p)
            frontier = nxt
            if not frontier:
                break
        return seen

    for r in data["relationships"]:
        a = str(r.get("a", "")).strip()
        b = str(r.get("b", "")).strip()
        kind = str(r.get("type", "")).strip()
        if not a or not b:
            continue
        if a == b:
            issues.append(f"❌ 관계 오류: {a}가 자기 자신과 '{kind}' 관계입니다.")
            continue
        if a not in chars or b not in chars:
            issues.append(f"⚠️ 관계 '{a} - {b}' 중 인물 목록에 없는 이름이 있습니다.")
            continue
        if kind in {"부부", "연인", "약혼", "결혼"}:
            if b in ancestors(a) or a in ancestors(b):
                issues.append(f"❌ 혈연 오류: {a}와 {b}는 직계혈족인데 '{kind}' 관계입니다.")
            shared = parents(a) & parents(b)
            if shared:
                issues.append(
                    f"❌ 혈연 오류: {a}와 {b}는 공통 부모({', '.join(shared)})가 있는데 '{kind}' 관계입니다."
                )

    for e in data["timeline"]:
        if isinstance(e.get("year"), int):
            actor = str(e.get("person", "")).strip()
            if actor in chars and isinstance(chars[actor].get("birth_year"), int):
                if e["year"] < chars[actor]["birth_year"]:
                    issues.append(
                        f"❌ 연표 오류: {actor}의 사건({e['year']})이 출생연도({chars[actor]['birth_year']})보다 빠릅니다."
                    )

    episode_count = int(data["meta"].get("episode_count", 10) or 10)
    for f in data["foreshadowing"]:
        p = int(f.get("planted_episode", 1) or 1)
        q = int(f.get("payoff_episode", p) or p)
        if q < p:
            issues.append(f"❌ 떡밥 '{f.get('clue','')}'의 회수 화가 심는 화보다 빠릅니다.")
        if q > episode_count:
            issues.append(
                f"⚠️ 떡밥 '{f.get('clue','')}'의 회수 예정 {q}화가 총 {episode_count}부작을 넘습니다."
            )

    if not issues:
        issues.append("✅ 규칙 기반 검사에서 즉시 드러나는 설정 오류를 찾지 못했습니다.")
    return issues



def deterministic_repair_project_data(data):
    """2.8.3: AI 없이 안전하게 고칠 수 있는 구조 오류만 정리한다.
    Canon 의미를 추론하지 않고, 명백한 무효값/스키마 오류만 보정한다.
    """
    changes = []

    # 인물: 빈 이름 제거, age/birth_year의 0/음수만 미확정(None)으로 정리.
    cleaned_chars = []
    for c in data.get("characters", []):
        if not isinstance(c, dict):
            changes.append("인물표의 비객체 행 제거")
            continue
        name = str(c.get("name", "")).strip()
        if not name:
            changes.append("이름 없는 인물 행 제거")
            continue
        row = dict(c)
        for key in ("age", "birth_year"):
            val = row.get(key)
            if isinstance(val, (int, float)) and val <= 0:
                row[key] = None
                changes.append(f"{name}.{key}: {val} → null")
        cleaned_chars.append(row)
    data["characters"] = cleaned_chars

    # 관계: 빈 행/자기 자신 관계는 명백한 구조 오류이므로 제거한다.
    cleaned_rel = []
    for r in data.get("relationships", []):
        if not isinstance(r, dict):
            changes.append("관계표의 비객체 행 제거")
            continue
        a, b = str(r.get("a", "")).strip(), str(r.get("b", "")).strip()
        if not a or not b:
            changes.append("주체가 비어 있는 관계 행 제거")
            continue
        if a == b:
            changes.append(f"자기 자신 관계 제거: {a}")
            continue
        cleaned_rel.append(r)
    data["relationships"] = cleaned_rel

    # 연표: known_by는 문자열 또는 문자열 배열만 허용. 그 외는 빈 값으로 정규화.
    for e in data.get("timeline", []):
        if not isinstance(e, dict):
            continue
        kb = e.get("known_by")
        if kb is None:
            e["known_by"] = ""
            changes.append("연표 known_by: null → 빈 문자열")
        elif isinstance(kb, list):
            vals = [str(x).strip() for x in kb if str(x).strip()]
            e["known_by"] = ", ".join(dict.fromkeys(vals))
            changes.append("연표 known_by 배열 → 문자열 정규화")
        elif not isinstance(kb, str):
            e["known_by"] = str(kb)
            changes.append("연표 known_by 타입 정규화")

    # 정보 장부: learned_episode 음수는 0, 총 회차 초과는 마지막 화로 제한.
    total = int(data.get("meta", {}).get("episode_count", 10) or 10)
    for k in data.get("knowledge", []):
        if not isinstance(k, dict):
            continue
        try:
            ep = int(k.get("learned_episode", 0) or 0)
        except Exception:
            ep = 0
        fixed = min(max(ep, 0), total)
        if fixed != ep:
            changes.append(f"정보 장부 learned_episode: {ep} → {fixed}")
        k["learned_episode"] = fixed

    # 떡밥 회차는 작품 범위를 벗어나지 않도록 정규화하되 순서는 뒤집지 않는다.
    for f in data.get("foreshadowing", []):
        if not isinstance(f, dict):
            continue
        try:
            p = int(f.get("planted_episode", 1) or 1)
        except Exception:
            p = 1
        try:
            q = int(f.get("payoff_episode", p) or p)
        except Exception:
            q = p
        p2 = min(max(p, 1), total)
        q2 = min(max(q, p2), total)
        if (p2, q2) != (p, q):
            changes.append(f"떡밥 회차 정규화: {p}/{q} → {p2}/{q2}")
        f["planted_episode"] = p2
        f["payoff_episode"] = q2

    return changes


def split_repair_issues(issues):
    """감사 지적을 구조/서사 문제로 나눠 하이브리드 보정에 사용한다."""
    structural, narrative = [], []
    structural_words = [
        "인물표", "나이", "age", "birth_year", "known_by", "관계표", "연표",
        "정보 장부", "지식 장부", "떡밥 장부", "스키마", "필드", "데이터"
    ]
    for issue in issues:
        blob = " ".join(str(issue.get(k, "")) for k in ("problem", "required_fix", "target_fields")).lower()
        if any(w.lower() in blob for w in structural_words):
            structural.append(issue)
        else:
            narrative.append(issue)
    return structural, narrative


def count_audit_items(text):
    """화면용 단순 지표. 감사 보고서의 번호형 문제 개수를 센다."""
    if not text:
        return 0
    nums = re.findall(r"(?m)^\s*(?:\d+)[\.)]\s+", str(text))
    return len(nums)


def upsert_knowledge(data, rows):
    for row in rows:
        if not isinstance(row, dict):
            continue
        person = str(row.get("person", "")).strip()
        fact = str(row.get("fact", "")).strip()
        if not person or not fact:
            continue
        exists = any(
            k.get("person") == person and k.get("fact") == fact
            for k in data["knowledge"]
        )
        if not exists:
            data["knowledge"].append({
                "person": person,
                "fact": fact,
                "learned_episode": int(row.get("learned_episode", 1) or 1),
                "source": str(row.get("source", "")).strip(),
            })



def normalize_bible_payload(payload, episode_count=10):
    if not isinstance(payload, dict):
        raise ValueError("Story Bible JSON 객체가 아닙니다.")
    meta = payload.get("meta", {}) if isinstance(payload.get("meta"), dict) else {}
    meta.setdefault("title", "새 드라마")
    meta.setdefault("genre", "")
    meta.setdefault("format", f"숏폼 {episode_count}부작")
    meta.setdefault("tone", "")
    meta.setdefault("premise", "")
    meta.setdefault("final_truth", "")
    meta["episode_count"] = int(meta.get("episode_count", episode_count) or episode_count)
    def only_dicts(name):
        rows = payload.get(name, [])
        return [x for x in rows if isinstance(x, dict)] if isinstance(rows, list) else []
    return {"meta":meta,"characters":only_dicts("characters"),"relationships":only_dicts("relationships"),"timeline":only_dicts("timeline"),"foreshadowing":only_dicts("foreshadowing"),"knowledge":only_dicts("knowledge")}

def apply_bible_to_project(data, bible):
    data["meta"].update(bible["meta"])
    data["characters"] = bible["characters"]
    data["relationships"] = bible["relationships"]
    data["timeline"] = bible["timeline"]
    data["foreshadowing"] = bible["foreshadowing"]
    data["knowledge"] = bible["knowledge"]
    data["season_plan"] = []
    data["episodes"] = []
    data["season_locked"] = False
    data["season_audit"] = ""

def refine_canon_master(api_key, model, data, source_text=None):
    """검증/수정 이력을 제거하고 최종 확정 사실만 Canon 문서로 정제한다."""
    lab = data["concept_lab"]
    source = (source_text or lab.get("revised") or lab.get("locked_bible") or "").strip()
    if not source:
        raise ValueError("정제할 확정 기획이 없습니다.")
    rules = json.dumps(data.get("writer_rules", []), ensure_ascii=False, indent=2)
    external = "\n\n".join(str(x) for x in lab.get("external_checks", []) if str(x).strip())
    raw = call_model(api_key, model,
        """당신은 드라마 제작실의 Canon 편집자다. 입력에는 최종 기획뿐 아니라 검증 보고서, 수정 이유, 변경 이력, 자기점검 문구가 섞여 있을 수 있다.
당신의 임무는 '작품 세계에서 실제로 참인 최종 설정'만 추출해 하나의 깨끗한 Canon 문서로 만드는 것이다.

절대 규칙:
- 검증 보고서, REVISE/PASS 판정, 수정 이유, 패치 범위, 보완 회차, 자기점검 문구는 Canon에 넣지 않는다.
- 입력에 없는 새 인물, 새 친자관계, 새 범인, 새 사망, 새 반전을 만들지 않는다.
- 서로 다른 과거안이 충돌하면 가장 뒤에 명시된 최종 통합 기획을 우선한다.
- [외부 확인 필요]인 법률·제도·의학·회사 실무는 확정 사실로 승격하지 않고 반드시 별도 '외부 확인 필요' 섹션에 남긴다.
- 최종 반전과 작가만 아는 진실은 빠뜨리지 않는다.
- 설명이나 평가 없이 Canon 문서만 출력한다.""",
        f"""정제 대상 원문:
{source}

외부 확인 기록(있으면 참고하되 검증 보고서 자체를 복사하지 말 것):
{external or '없음'}

작가실 규칙:
{rules}

다음 순서의 Markdown Canon 문서로 정리하라.
# 작품 Canon
## 작품 개요
- 제목
- 장르/형식
- 공개 로그라인

## 절대 변경 금지 진실
최종 반전, 실제 친자/사망/혼인/범인 등 작가만 아는 확정 사실.

## 인물
각 인물의 역할, 욕망, 약점, 비밀.

## 관계
확정된 관계와 서로의 오인/비밀을 구분.

## 시간선
사건 발생 순서와 필요한 시점.

## 회사/권력 구조
작품에서 확정한 직위와 권력관계만. 외부 확인이 필요한 세부 법률효과는 확정하지 말 것.

## 1~10화 핵심 사건
회차별 확정 사건만 간결하게.

## 떡밥과 회수
심어야 할 단서와 회수 시점.

## 집필 금지/주의
확정 설정을 깨는 대표적 금지사항.

## 외부 확인 필요
아직 미확정인 전문 사실만 항목화.

검증 과정이나 수정 이력은 절대 포함하지 마라.""")
    text = raw.strip()
    if not text:
        raise ValueError("Canon 정제 결과가 비어 있습니다.")
    return text


def build_bible_from_locked_concept(api_key, model, data):
    lab = data["concept_lab"]
    locked = (lab.get("canon_master") or lab.get("locked_bible", "")).strip()
    if not locked:
        raise ValueError("잠금된 Canon이 없습니다.")
    rules = json.dumps(data.get("writer_rules", []), ensure_ascii=False, indent=2)
    total = int(data.get("meta", {}).get("episode_count", 10) or 10)
    raw = call_model(api_key, model,
        """당신은 드라마 제작실의 Story Bible 편집자다. 정제된 Canon의 사실을 바꾸지 말고 구조화만 한다. 새로운 핵심 반전, 친자관계, 범인, 혼인관계, 사망 여부를 임의로 추가하지 않는다. 불확실한 전문 사실을 확정 사실로 승격하지 않는다. 출력은 설명 없이 오직 유효한 JSON 객체 하나만 반환한다.""",
        f"""잠금된 기획:\n{locked}\n\n작가실 규칙:\n{rules}\n\n다음 JSON 스키마로 구조화하라.\n{{\n  \"meta\": {{\"title\":\"제목\",\"genre\":\"장르\",\"format\":\"숏폼 {total}부작, 회당 분량\",\"tone\":\"톤과 문체\",\"premise\":\"공개 가능한 기본 설정/로그라인\",\"final_truth\":\"작가만 아는 전체 진실\",\"episode_count\":{total}}},\n  \"characters\": [{{\"name\":\"이름\",\"age\":35,\"birth_year\":null,\"role\":\"역할\",\"biological_mother\":\"\",\"biological_father\":\"\",\"raised_by\":\"\",\"secret\":\"숨기는 사실\",\"desire\":\"욕망/목표\"}}],\n  \"relationships\": [{{\"a\":\"인물A\",\"b\":\"인물B\",\"type\":\"관계\",\"detail\":\"설명\"}}],\n  \"timeline\": [{{\"year\":\"시점 또는 연도\",\"event\":\"사건\",\"person\":\"관련 인물\",\"known_by\":\"현재 알고 있는 인물\"}}],\n  \"foreshadowing\": [{{\"clue\":\"떡밥\",\"planted_episode\":1,\"payoff_episode\":5,\"truth\":\"실제 의미\",\"status\":\"미회수\"}}],\n  \"knowledge\": [{{\"person\":\"인물\",\"fact\":\"본편 시작 전에 이미 아는 사실\",\"learned_episode\":0,\"source\":\"알게 된 이유\"}}]\n}}\n잠금 기획에 없는 구체적 혈연/법률관계를 임의 생성하지 마라. final_truth에는 잠금 기획의 정답을 빠뜨리지 마라. premise에는 최종 반전을 노출하지 마라.
외부 확인이 필요하다고 표시된 법률·제도 사항은 확정 Canon 사실처럼 구체화하지 말고, 필요하면 일반적 표현으로 유지하라.""")
    return normalize_bible_payload(extract_json(raw), total)

def build_audit_digest(api_key, model, audit_text):
    """긴 레드팀 보고서를 사용자가 빠르게 판단할 수 있는 JSON 요약으로 변환한다."""
    raw = call_model(
        api_key, model,
        """당신은 드라마 기획 검수 보고서 편집자다. 원문에 없는 문제를 새로 만들지 않는다.
출력은 설명 없이 유효한 JSON 객체 하나만 반환한다.""",
        f"""다음 공격검증 보고서를 짧게 구조화하라.

{audit_text}

스키마:
{{
  "verdict":"PASS|REVISE|REJECT|UNKNOWN",
  "critical_count":0,
  "important_count":0,
  "minor_count":0,
  "issues":[
    {{"severity":"치명적|중요|경미","title":"15자 안팎 제목","problem":"한두 문장","fix_direction":"한 문장","external_check":false}}
  ]
}}
규칙: issues는 가장 중요한 것부터 최대 8개. 법률/제도 등 외부 확인이 필요하면 external_check=true."""
    )
    obj = extract_json(raw)
    return obj if isinstance(obj, dict) else {}


def render_audit_digest(digest):
    if not isinstance(digest, dict) or not digest:
        return
    verdict = str(digest.get("verdict", "UNKNOWN"))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("판정", verdict)
    c2.metric("🔴 치명적", int(digest.get("critical_count", 0) or 0))
    c3.metric("🟠 중요", int(digest.get("important_count", 0) or 0))
    c4.metric("🟡 경미", int(digest.get("minor_count", 0) or 0))
    for i, issue in enumerate(digest.get("issues", [])[:8], 1):
        sev = issue.get("severity", "중요")
        icon = {"치명적":"🔴", "중요":"🟠", "경미":"🟡"}.get(sev, "⚪")
        ext = " · 외부 확인 필요" if issue.get("external_check") else ""
        with st.expander(f"{icon} {i}. {issue.get('title','문제')} ({sev}{ext})"):
            st.write(issue.get("problem", ""))
            if issue.get("fix_direction"):
                st.caption("수정 방향")
                st.write(issue.get("fix_direction"))


def creative_controls_text(data):
    c = data.get("creative_controls", {})
    return (f"막장도 {c.get('makjang',8)}/10, 반전 강도 {c.get('twist',8)}/10, "
            f"현실성 {c.get('realism',7)}/10, 법률 정확성 {c.get('legal_accuracy',6)}/10")

st.set_page_config(
    page_title="AI 드라마 작가실 2.0",
    page_icon="🎬",
    layout="wide"
)

st.title("🎬 AI 드라마 작가실 2.8.3")
st.caption("한 줄 아이디어 → 재미/현실성 조절 → 레드팀 → 사용자 승인 → Canon 잠금 → 시즌/대본")

if "data" not in st.session_state:
    st.session_state.data = load_data()

data = st.session_state.data

with st.sidebar:
    st.header("AI 설정")
    api_key = st.text_input(
        "OpenAI API Key",
        type="password",
        value=os.getenv("OPENAI_API_KEY", "")
    )
    model = st.selectbox(
        "모델",
        ["gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.6"],
        index=0
    )
    st.caption("Terra: 균형 · Sol: 고난도 설계/검수 · Luna: 비용 절약")

    if st.button("💾 전체 저장", use_container_width=True):
        save_data(data)
        st.success("저장했습니다.")

    export_json = json.dumps(data, ensure_ascii=False, indent=2)
    st.download_button(
        "⬇️ 프로젝트 JSON",
        export_json,
        file_name=f"{slugify(data['meta'].get('title','project'))}.json",
        mime="application/json",
        use_container_width=True
    )

    upload = st.file_uploader("프로젝트 JSON 불러오기", type=["json"])
    if upload is not None:
        try:
            imported = migrate_data(json.loads(upload.getvalue().decode("utf-8")))
            if st.button("이 프로젝트로 교체", use_container_width=True):
                st.session_state.data = imported
                save_data(imported)
                st.rerun()
        except Exception as e:
            st.error(f"JSON 오류: {e}")

tabs = st.tabs([
    "🧪 기획 검증실",
    "📚 작가실 규칙",
    "작품",
    "인물",
    "관계",
    "연표",
    "떡밥",
    "🧠 정보 장부",
    "🗺️ 전체 설계",
    "✍️ 회차 집필",
    "🔎 설정 감사",
])


# 0. 기획 검증실
with tabs[0]:
    st.subheader("🧪 기획 검증실")
    st.caption("바로 대본을 쓰지 않습니다. 먼저 설정을 만들고 공격 검증합니다. AI 수정은 '제안'일 뿐이며, 사용자가 승인해야 Canon 후보가 됩니다.")
    lab = data["concept_lab"]

    st.markdown("### 🎚️ 작품 성향")
    cc = data["creative_controls"]
    a,b,c,d = st.columns(4)
    cc["makjang"] = a.slider("막장도", 1, 10, int(cc.get("makjang",8)), help="높을수록 관계 충돌·감정 폭발을 우선")
    cc["twist"] = b.slider("반전 강도", 1, 10, int(cc.get("twist",8)), help="높을수록 회차별 뒤집기와 재해석을 강화")
    cc["realism"] = c.slider("현실성", 1, 10, int(cc.get("realism",7)), help="높을수록 우연·편의적 행동을 엄격히 제한")
    cc["legal_accuracy"] = d.slider("법률 정확성", 1, 10, int(cc.get("legal_accuracy",6)), help="높을수록 법·상속·회사 절차를 보수적으로 다룸")
    st.caption("법률 정확성이 낮아도 거짓 법률을 만들어도 된다는 뜻은 아닙니다. 불확실하면 '외부 확인 필요'로 남깁니다.")
    save_data(data)

    lab["brief"] = st.text_area(
        "만들고 싶은 드라마",
        lab.get("brief", ""),
        height=120,
        placeholder="예: 한국 현대 배경의 치정 막장. 10부작 숏폼. 불륜·재산·복수 중심. 현실적으로 성립해야 함."
    )

    c1, c2 = st.columns(2)
    if c1.button("① 기획 초안 만들기", use_container_width=True):
        if not api_key:
            st.error("OpenAI API Key가 필요합니다.")
        elif not lab["brief"].strip():
            st.error("먼저 원하는 드라마를 한두 문장으로 입력하세요.")
        else:
            rules = json.dumps(data["writer_rules"], ensure_ascii=False, indent=2)
            lab["candidate"] = call_model(
                api_key, model,
                """당신은 한국 드라마 기획자다. 자극성보다 먼저 성립 가능한 사건 구조를 만든다.
현대 한국의 혼인·상속·친자·수사·회사·의료 등 현실 제도를 임의로 왜곡하지 않는다.
모르는 전문 사실은 단정하지 말고 검증 필요 항목으로 표시한다.
사용자의 장르 요구를 살리되 우연과 바보 같은 행동으로 플롯을 유지하지 않는다.""",
                f"""요청:
{lab['brief']}

작가실 규칙:
{rules}

작품 성향:
{creative_controls_text(data)}

우선순위 원칙:
- 막장도/반전이 높아도 현실성 검증을 통과해야 한다.
- 현실성/법률 정확성이 높아도 설명문과 절차가 드라마의 중심이 되지 않게 한다.
- 정확한 지분율·금액·법률 용어는 이야기상 꼭 필요하고 근거가 있을 때만 사용한다.

하나의 가장 강한 기획안을 작성하라.
반드시 포함:
- 한 줄 로그라인
- 핵심 인물과 각자의 욕망
- 치정 관계
- 사건의 발단
- 숨겨진 진실
- 비밀이 지금까지 유지된 구체적 이유
- 돈/상속/혼인/친자 등 현실 장치의 작동 방식
- 최종 반전과 그 원인
- 10화 결말
- 아직 외부 사실 확인이 필요한 항목
아직 '확정'이라고 부르지 마라."""
            )
            lab["audit"] = ""
            lab["audit_digest"] = {}
            lab["revised"] = ""
            lab["revision_approved"] = False
            lab["reaudit"] = ""
            lab["refine_note"] = ""
            lab["refine_round"] = 0
            lab["refine_history"] = []
            lab["external_checks"] = []
            lab["conditional_canon"] = False
            lab["locked"] = False
            lab["locked_bible"] = ""
            save_data(data)
            st.rerun()

    if lab.get("candidate"):
        st.markdown("### 기획 초안")
        st.write(lab["candidate"])

        if c2.button("② 설정 공격검증", use_container_width=True):
            rules = json.dumps(data["writer_rules"], ensure_ascii=False, indent=2)
            lab["audit"] = call_model(
                api_key, model,
                """당신은 기획안을 통과시키는 사람이 아니라 탈락시키는 레드팀이다.
재미를 칭찬하지 말고 시청자가 '말이 안 된다'고 할 지점을 먼저 찾는다.
법률적 결론이 핵심이면 확실하지 않은 내용을 지어내지 말고 '외부 확인 필요'라고 표시한다.
문제의 심각도를 치명적/중요/경미로 구분한다.""",
                f"""기획안:
{lab['candidate']}

영구 규칙:
{rules}

작품 성향:
{creative_controls_text(data)}

다음 순서로 공격 검증하라:
1. 현실/법률/제도 성립성
2. 시간선과 나이
3. 비밀 유지 가능성
4. 돈과 재산의 흐름
5. 인물 동기
6. '왜 그냥 이렇게 하지 않았나?' 대안 행동
7. 반전의 공정성 및 사전 단서
8. 우연/편의적 행동
9. 서로 충돌하는 사실
10. 외부 사실 확인이 필요한 주장
마지막에 PASS / REVISE / REJECT 중 하나와 이유를 적어라."""
            )
            try:
                lab["audit_digest"] = build_audit_digest(api_key, model, lab["audit"])
            except Exception:
                lab["audit_digest"] = {}
            save_data(data)
            st.rerun()

    if lab.get("audit"):
        st.markdown("### 공격검증 요약")
        render_audit_digest(lab.get("audit_digest", {}))
        with st.expander("전체 공격검증 보고서 보기"):
            st.write(lab["audit"])
        lab["revision_note"] = st.text_area(
            "수정 제안에 반영할 내 지시 (선택)",
            lab.get("revision_note", ""),
            placeholder="예: 핵심 불륜 관계는 유지. 기업 지분 숫자는 만들지 말 것. 감정 갈등을 더 세게."
        )
        if st.button("③ AI 수정 제안 보기", use_container_width=True):
            rules = json.dumps(data["writer_rules"], ensure_ascii=False, indent=2)
            lab["revised"] = call_model(
                api_key, model,
                """당신은 드라마 쇼러너다. 당신은 확정권자가 아니라 수정안을 제안하는 사람이다.
레드팀의 치명적/중요 지적만 최소 변경으로 해결한다.
원래 기획의 핵심 훅, 관계, 장르적 재미를 최대한 보존한다.
새로운 인물·과거 사건·지분율·법률 장치·친자관계·범인·사망을 꼭 필요하지 않으면 추가하지 않는다.
새 설정이 불가피하면 반드시 '신규 제안'이라고 표시하고 이유를 적는다.
현실성이 불확실한 전문 사실은 '외부 확인 필요'로 남긴다.
절대 스스로 확정했다고 말하지 않는다.""",
                f"""원 기획:
{lab['candidate']}

공격검증:
{lab['audit']}

규칙:
{rules}

작품 성향:
{creative_controls_text(data)}

사용자 추가 지시:
{lab.get('revision_note','') or '없음'}

다음 형식으로 작성하라:
1) 유지되는 핵심 설정
2) 변경 제안 (각 항목: 기존 → 제안 → 이유)
3) 신규 제안 (없으면 '없음')
4) 외부 확인 필요
5) 수정 통합 기획안
6) 재미 손실 점검: 검증 때문에 이야기가 법무/절차극으로 변했는지 평가

정확한 숫자·지분율·법률 절차는 꼭 필요한 경우가 아니면 만들지 마라."""
            )
            lab["revision_approved"] = False
            lab["reaudit"] = ""
            lab["refine_note"] = ""
            lab["refine_round"] = 0
            lab["refine_history"] = []
            lab["external_checks"] = []
            lab["conditional_canon"] = False
            save_data(data)
            st.rerun()

    if lab.get("revised"):
        st.markdown("### AI 수정 제안 — 아직 확정 아님")
        st.warning("아래 내용은 AI 제안입니다. 승인 전에는 Story Bible이나 Canon에 반영되지 않습니다.")
        st.write(lab["revised"])
        # 2.6: 국소 보완 뒤에는 다음 행동을 명시적으로 보여준다.
        if int(lab.get("refine_round", 0)) > 0 and not lab.get("revision_approved", False):
            st.info(f"🔄 {lab.get('refine_round',0)}차 국소 보완이 끝났습니다. 보완안을 승인한 뒤 독립 재검증을 다시 실행하세요.")
        c_yes, c_no = st.columns(2)
        approve_label = "🔄 보완안 승인하고 독립 재검증" if int(lab.get("refine_round", 0)) > 0 else "✅ 이 수정안을 승인하고 재검증"
        if c_yes.button(approve_label, use_container_width=True):
            lab["revision_approved"] = True
            rules = json.dumps(data["writer_rules"], ensure_ascii=False, indent=2)
            lab["reaudit"] = call_model(
                api_key, model,
                """당신은 두 번째 독립 레드팀이다. 이전 검토자의 결론을 믿지 말고 처음부터 다시 검사한다.
치명적 오류가 하나라도 있으면 PASS를 주지 않는다.
검증 때문에 이야기의 장르적 훅과 감정 엔진이 사라졌다면 그것도 중요한 결함으로 본다.
현실/법률 전문 사실이 핵심인데 확인되지 않았으면 CONDITIONAL PASS 또는 REVISE로 표시한다.""",
                f"""사용자가 승인한 수정 기획 후보:
{lab['revised']}

원 기획:
{lab['candidate']}

규칙:
{rules}

작품 성향:
{creative_controls_text(data)}

현실성, 법률/제도, 시간선, 비밀 유지, 인물 동기, 인과관계, 반전 공정성,
우연성, 기존 사실 충돌, 원래 핵심 훅 보존 여부를 독립적으로 재검증하라.
정확한 숫자나 전문 절차가 불필요하게 추가되었으면 지적하라.
마지막 줄은 반드시 VERDICT: PASS / CONDITIONAL PASS / REVISE / REJECT 중 하나."""
            )
            save_data(data)
            st.rerun()
        if c_no.button("↩️ 승인하지 않고 새 수정 제안", use_container_width=True):
            lab["revised"] = ""
            lab["revision_approved"] = False
            lab["reaudit"] = ""
            save_data(data)
            st.rerun()

    if lab.get("reaudit"):
        st.markdown("### 독립 재검증")
        st.write(lab["reaudit"])

        verdict_text = lab["reaudit"].upper()
        verdict_pass = "VERDICT: PASS" in verdict_text and "CONDITIONAL PASS" not in verdict_text and lab.get("revision_approved", False)
        verdict_conditional = "VERDICT: CONDITIONAL PASS" in verdict_text and lab.get("revision_approved", False)
        verdict_needs_work = ("VERDICT: REVISE" in verdict_text or "VERDICT: REJECT" in verdict_text or verdict_conditional)

        if verdict_pass:
            st.success("독립 재검증 PASS. 이제 사용자가 최종 승인하면 Canon으로 잠글 수 있습니다.")

        if verdict_needs_work:
            st.warning("현재 승인본을 유지하고, 재검증에서 실패한 항목만 국소 보완할 수 있습니다.")
            lab["refine_note"] = st.text_area(
                "보완 지시 (선택)",
                lab.get("refine_note", ""),
                placeholder="예: 통과한 친자 시간선과 핵심 반전은 건드리지 말고, DNA 검사 회피 이유와 이사회 권력 구조만 보완."
            )
            if st.button("🔧 지적사항만 보완하기", use_container_width=True):
                if not api_key:
                    st.error("OpenAI API Key가 필요합니다.")
                else:
                    rules = json.dumps(data["writer_rules"], ensure_ascii=False, indent=2)
                    previous = lab["revised"]
                    refined = call_model(
                        api_key, model,
                        """당신은 드라마 기획의 국소 수정 편집자다.
현재 사용자가 승인한 기획의 이미 통과한 항목은 잠긴 것으로 취급한다.
재검증 보고서에서 '보완 필요', '필수 수정', '핵심 검증 필요'로 남은 항목만 최소 수정한다.
이미 '통과' 또는 '대체로 통과'한 설정, 핵심 훅, 인물 관계, 최종 반전, 시간선을 임의로 바꾸지 않는다.
새 인물, 새 친자관계, 새 사망, 새 범인, 구체적 지분율·금액·법률 절차를 불필요하게 추가하지 않는다.
전문 사실이 외부 확인을 필요로 하면 억지로 확정하지 말고 [외부 확인 필요]로 표시한다.
수정 뒤에는 무엇을 유지했고 무엇만 바꿨는지 분명히 적는다.""",
                        f"""현재 승인 기획:
{previous}

독립 재검증 보고서:
{lab['reaudit']}

작가실 규칙:
{rules}

작품 성향:
{creative_controls_text(data)}

사용자 추가 보완 지시:
{lab.get('refine_note','') or '없음'}

출력 형식:
1) 절대 유지한 항목
2) 이번에 보완한 항목 (재검증 지적 → 수정 → 이유)
3) 외부 확인 필요 항목
4) 보완된 통합 기획안
5) 변경 범위 점검: 통과 항목을 건드렸는지 스스로 확인

핵심 원칙: '전면 재작성'이 아니라 '실패 항목 패치'다."""
                    )
                    history = lab.get("refine_history", [])
                    if not isinstance(history, list):
                        history = []
                    history.append({
                        "round": int(lab.get("refine_round", 0)) + 1,
                        "before": previous,
                        "audit": lab["reaudit"],
                        "after": refined,
                        "at": datetime.now().isoformat(timespec="seconds"),
                    })
                    lab["refine_history"] = history[-6:]
                    lab["refine_round"] = int(lab.get("refine_round", 0)) + 1
                    lab["revised"] = refined
                    lab["revision_approved"] = False
                    lab["reaudit"] = ""
                    lab["conditional_canon"] = False
                    # 2.6: refined text becomes a fresh Canon candidate; user must explicitly approve it
                    # and the same independent red-team audit is run again from the revised candidate.
                    save_data(data)
                    st.rerun()

        if verdict_conditional:
            st.info("조건부 통과입니다. 이야기 논리는 충분하지만, 법률·제도 등 외부 사실 확인이 남아 있을 수 있습니다.")
            if st.button("⚠️ 외부 확인 항목을 남기고 조건부 Canon 허용", use_container_width=True):
                lab["conditional_canon"] = True
                # 보고서 자체를 검증 필요 기록으로 남긴다. Story Bible 변환 시에도 모델이 확정 사실로 승격하지 않도록 한다.
                lab["external_checks"] = [lab["reaudit"]]
                save_data(data)
                st.rerun()

        can_lock = verdict_pass or (verdict_conditional and lab.get("conditional_canon", False))
        if can_lock:
            if lab.get("conditional_canon", False):
                st.warning("조건부 Canon: 외부 확인이 끝나지 않은 전문 사실은 미확정 상태입니다. 집필 시 단정적으로 사용하지 않습니다.")
            if st.button("🔒 이 설정 확정 + Story Bible 자동 생성", type="primary", use_container_width=True):
                if not api_key:
                    st.error("OpenAI API Key가 필요합니다.")
                else:
                    lab["locked"] = True
                    lab["raw_locked_candidate"] = lab["revised"]
                    lab["locked_at"] = datetime.now().isoformat(timespec="seconds")
                    data["season_locked"] = False
                    save_data(data)
                    with st.status("Canon 정제 → Story Bible 자동 생성 중", expanded=True) as status:
                        try:
                            canon = refine_canon_master(api_key, model, data, lab["raw_locked_candidate"])
                            lab["canon_master"] = canon
                            lab["canon_refined_at"] = datetime.now().isoformat(timespec="seconds")
                            # 하위 기능과 구버전 호환을 위해 locked_bible도 정제 Canon만 가리킨다.
                            lab["locked_bible"] = canon
                            save_data(data)
                            status.write("검증 보고서·수정 이력을 제거하고 최종 설정만 Canon으로 정제했습니다.")
                            bible = build_bible_from_locked_concept(api_key, model, data)
                            apply_bible_to_project(data, bible)
                            save_data(data)
                            status.update(label="Canon 정제 + Story Bible 생성 완료", state="complete")
                            st.success("최종 Canon만 기준으로 작품·인물·관계·연표·떡밥·정보 장부를 다시 구축했습니다.")
                        except Exception as e:
                            lab["locked"] = False
                            lab["canon_master"] = ""
                            lab["canon_refined_at"] = ""
                            lab["locked_bible"] = ""
                            lab["locked_at"] = ""
                            save_data(data)
                            status.update(label="Canon 정제/Story Bible 생성 실패", state="error")
                            st.error(f"자동 정제 오류: {e}")

    if lab.get("refine_round", 0):
        st.caption(f"국소 보완 {lab.get('refine_round',0)}회 수행 · 통과 항목 보존 모드")
        with st.expander("보완 이력 보기"):
            for h in lab.get("refine_history", []):
                st.write(f"**{h.get('round')}차 보완 · {h.get('at','')}**")
                st.write(h.get("after",""))

    if lab.get("locked"):
        st.divider()
        if lab.get("conditional_canon", False):
            st.warning(f"⚠️ 조건부 Story Bible 잠금 완료 · {lab.get('locked_at','')}")
        else:
            st.success(f"🔒 Story Bible 잠금 완료 · {lab.get('locked_at','')}")

        # 2.6에서 이미 잠근 프로젝트는 검증/수정 이력이 locked_bible에 섞여 있을 수 있다.
        # 2.7에서는 한 번의 버튼으로 최종 설정만 정제하고 구조화 장부도 다시 만든다.
        if not lab.get("canon_master", "").strip():
            st.warning("2.6 형식의 잠금 데이터입니다. 집필 전에 검증 이력을 제거한 최종 Canon으로 정제하세요.")
            if st.button("✨ 기존 Canon 정제 + Story Bible 재생성", type="primary", use_container_width=True):
                if not api_key:
                    st.error("OpenAI API Key가 필요합니다.")
                else:
                    source = (lab.get("raw_locked_candidate") or lab.get("locked_bible") or lab.get("revised") or "").strip()
                    with st.status("기존 잠금본 Canon 정제 중", expanded=True) as status:
                        try:
                            lab["raw_locked_candidate"] = source
                            canon = refine_canon_master(api_key, model, data, source)
                            lab["canon_master"] = canon
                            lab["canon_refined_at"] = datetime.now().isoformat(timespec="seconds")
                            lab["locked_bible"] = canon
                            bible = build_bible_from_locked_concept(api_key, model, data)
                            apply_bible_to_project(data, bible)
                            save_data(data)
                            status.update(label="Canon 정제 + Story Bible 재생성 완료", state="complete")
                            st.rerun()
                        except Exception as e:
                            status.update(label="Canon 정제 실패", state="error")
                            st.error(f"Canon 정제 오류: {e}")
        else:
            st.success(f"✨ Canon 정제 완료 · {lab.get('canon_refined_at','')}")

        st.info(f"자동 구축됨: 인물 {len(data['characters'])}명 · 관계 {len(data['relationships'])}개 · 연표 {len(data['timeline'])}개 · 떡밥 {len(data['foreshadowing'])}개 · 초기 정보 {len(data['knowledge'])}개")
        with st.expander("✨ 정제된 최종 Canon 보기"):
            st.write(lab.get("canon_master") or lab.get("locked_bible", ""))
        with st.expander("🧾 검증·보완 이력 보기"):
            st.caption("이 영역은 작업 기록이며 이후 집필의 Canon 사실로 사용하지 않습니다.")
            if lab.get("reaudit"):
                st.write(lab.get("reaudit"))
            for h in lab.get("refine_history", []):
                st.write(f"**{h.get('round')}차 보완 · {h.get('at','')}**")
                st.write(h.get("after", ""))


# 0-2. 작가실 규칙
with tabs[1]:
    st.subheader("📚 작가실 규칙")
    st.caption("여기에 쌓인 규칙은 다음 작품의 기획·검증·집필에도 자동으로 전달됩니다.")

    for i, rule in enumerate(data["writer_rules"]):
        c1, c2 = st.columns([8, 1])
        c1.write(f"**{rule.get('id','')}** — {rule.get('text','')}")
        if c2.button("삭제", key=f"rule_del_{i}"):
            data["writer_rules"].pop(i)
            save_data(data)
            st.rerun()

    with st.form("add_rule", clear_on_submit=True):
        new_rule = st.text_area(
            "새 실패 규칙 추가",
            placeholder="예: 장기간 이중생활은 주거·통신·금융·가족 측면에서 들키지 않은 이유를 설명한다."
        )
        if st.form_submit_button("규칙 저장"):
            if new_rule.strip():
                nums = []
                for r in data["writer_rules"]:
                    m = re.search(r"(\\d+)$", r.get("id", ""))
                    if m:
                        nums.append(int(m.group(1)))
                rid = f"RULE-{(max(nums) if nums else 0)+1:03d}"
                data["writer_rules"].append({"id": rid, "text": new_rule.strip()})
                save_data(data)
                st.rerun()


# 1. 작품
with tabs[2]:
    st.subheader("작품 바이블 · 자동 생성 결과")
    c1, c2 = st.columns(2)
    with c1:
        data["meta"]["title"] = st.text_input("제목", data["meta"].get("title", ""))
        data["meta"]["genre"] = st.text_input("장르", data["meta"].get("genre", ""))
        data["meta"]["format"] = st.text_input("형식", data["meta"].get("format", ""))
        data["meta"]["episode_count"] = int(st.number_input(
            "총 회차",
            min_value=2,
            max_value=100,
            value=int(data["meta"].get("episode_count", 10) or 10)
        ))
    with c2:
        data["meta"]["tone"] = st.text_area(
            "톤 / 문체",
            data["meta"].get("tone", ""),
            height=145
        )
    data["meta"]["premise"] = st.text_area(
        "기본 설정 / 로그라인",
        data["meta"].get("premise", ""),
        height=140
    )
    data["meta"]["final_truth"] = st.text_area(
        "🔒 작가만 아는 최종 진실",
        data["meta"].get("final_truth", ""),
        height=180,
        help="최종 반전과 사건의 실제 진실. 회차별 공개 시점을 통제하는 기준입니다."
    )
    save_data(data)

# 2. 인물
with tabs[3]:
    st.subheader("인물 카드 · 자동 생성 결과")
    with st.expander("➕ 인물 추가", expanded=not data["characters"]):
        with st.form("add_character", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("이름")
            age = c2.number_input("현재 나이", 0, 120, 30)
            birth_year = c3.number_input("출생연도(모르면 0)", 0, 2100, 0)
            role = st.text_input("역할", placeholder="예: 강력계 형사 / 살인사건 용의자")
            bio_m = st.text_input("친모 이름")
            bio_f = st.text_input("친부 이름")
            raised_by = st.text_input("양육자/양육가족")
            secret = st.text_area("숨기는 비밀")
            desire = st.text_area("욕망 / 목표")
            if st.form_submit_button("인물 추가"):
                if name.strip():
                    data["characters"].append({
                        "name": name.strip(),
                        "age": int(age),
                        "birth_year": int(birth_year) if birth_year else None,
                        "role": role,
                        "biological_mother": bio_m.strip(),
                        "biological_father": bio_f.strip(),
                        "raised_by": raised_by.strip(),
                        "secret": secret,
                        "desire": desire,
                    })
                    save_data(data)
                    st.rerun()

    for i, c in enumerate(data["characters"]):
        with st.expander(f"{c.get('name','')} · {c.get('age','')}세 · {c.get('role','')}"):
            cols = st.columns(2)
            c["role"] = cols[0].text_input("역할", c.get("role", ""), key=f"role_{i}")
            c["age"] = int(cols[1].number_input(
                "현재 나이", 0, 120, int(c.get("age") or 0), key=f"age_{i}"
            ))
            c["biological_mother"] = cols[0].text_input(
                "친모", c.get("biological_mother", ""), key=f"bm_{i}"
            )
            c["biological_father"] = cols[1].text_input(
                "친부", c.get("biological_father", ""), key=f"bf_{i}"
            )
            c["raised_by"] = st.text_input(
                "양육자/양육가족", c.get("raised_by", ""), key=f"rb_{i}"
            )
            c["secret"] = st.text_area("비밀", c.get("secret", ""), key=f"secret_{i}")
            c["desire"] = st.text_area("욕망/목표", c.get("desire", ""), key=f"desire_{i}")
            if st.button("이 인물 삭제", key=f"delc_{i}"):
                data["characters"].pop(i)
                save_data(data)
                st.rerun()
    save_data(data)

# 3. 관계
with tabs[4]:
    st.subheader("관계도 · 자동 생성 결과")
    names = [c.get("name", "") for c in data["characters"] if c.get("name")]
    if len(names) >= 2:
        with st.form("add_rel", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            a = c1.selectbox("인물 A", names)
            b = c2.selectbox("인물 B", names, index=1)
            typ = c3.selectbox(
                "관계",
                ["부부", "연인", "약혼", "가족", "친구", "원수", "동료",
                 "상사-부하", "수사관-용의자", "의붓부모-자녀", "기타"]
            )
            detail = st.text_input("관계 설명")
            if st.form_submit_button("관계 추가"):
                if a != b:
                    data["relationships"].append({
                        "a": a, "b": b, "type": typ, "detail": detail
                    })
                    save_data(data)
                    st.rerun()
                else:
                    st.error("서로 다른 두 인물을 선택하세요.")
    else:
        st.info("인물을 2명 이상 추가하세요.")

    for i, r in enumerate(data["relationships"]):
        c1, c2 = st.columns([7, 1])
        c1.write(
            f"**{r.get('a')} ↔ {r.get('b')}** · {r.get('type')} · {r.get('detail','')}"
        )
        if c2.button("삭제", key=f"delr_{i}"):
            data["relationships"].pop(i)
            save_data(data)
            st.rerun()

# 4. 연표
with tabs[5]:
    st.subheader("사건 연표 · 자동 생성 결과")
    with st.form("timeline", clear_on_submit=True):
        c1, c2 = st.columns([1, 3])
        year_text = c1.text_input("연도/시점", placeholder="2001 또는 25년 전")
        event = c2.text_input("사건")
        person = st.text_input("관련 인물")
        knowledge = st.text_input("이 사건을 현재 알고 있는 인물")
        if st.form_submit_button("연표 추가"):
            year = int(year_text) if year_text.strip().isdigit() else year_text.strip()
            data["timeline"].append({
                "year": year,
                "event": event,
                "person": person,
                "known_by": knowledge,
            })
            save_data(data)
            st.rerun()

    for i, e in enumerate(data["timeline"]):
        c1, c2 = st.columns([7, 1])
        c1.write(
            f"**{e.get('year')}** — {e.get('event')} · 관련: {e.get('person','')} "
            f"· 알고 있음: {e.get('known_by','')}"
        )
        if c2.button("삭제", key=f"delt_{i}"):
            data["timeline"].pop(i)
            save_data(data)
            st.rerun()

# 5. 떡밥
with tabs[6]:
    st.subheader("떡밥 추적 장부 · 자동 생성 결과")
    with st.form("clue", clear_on_submit=True):
        clue = st.text_input("떡밥")
        c1, c2 = st.columns(2)
        planted = c1.number_input("심는 화", min_value=1, value=1)
        payoff = c2.number_input("회수 예정 화", min_value=1, value=5)
        truth = st.text_area("실제 의미 / 정답")
        if st.form_submit_button("떡밥 추가"):
            data["foreshadowing"].append({
                "clue": clue,
                "planted_episode": int(planted),
                "payoff_episode": int(payoff),
                "truth": truth,
                "status": "미회수",
            })
            save_data(data)
            st.rerun()

    for i, f in enumerate(data["foreshadowing"]):
        c1, c2, c3 = st.columns([5, 2, 1])
        c1.write(
            f"**{f.get('clue')}** · {f.get('planted_episode')}화 → "
            f"{f.get('payoff_episode')}화 · {f.get('truth','')}"
        )
        statuses = ["미회수", "부분회수", "회수완료"]
        old = f.get("status", "미회수")
        f["status"] = c2.selectbox(
            "상태",
            statuses,
            index=statuses.index(old) if old in statuses else 0,
            key=f"status_{i}"
        )
        if c3.button("삭제", key=f"delf_{i}"):
            data["foreshadowing"].pop(i)
            save_data(data)
            st.rerun()
    save_data(data)

# 6. 정보 장부
with tabs[7]:
    st.subheader("🧠 누가 무엇을 알고 있는가")
    st.caption("반전이 무너지는 가장 흔한 원인인 '알면 안 되는 사람이 먼저 아는 문제'를 추적합니다.")

    names = [c.get("name", "") for c in data["characters"] if c.get("name")]
    if names:
        with st.form("knowledge_add", clear_on_submit=True):
            person = st.selectbox("인물", names)
            fact = st.text_area("알게 된 사실")
            learned_ep = st.number_input("알게 된 회차", min_value=0, value=0,
                                         help="본편 시작 전부터 알았다면 0")
            source = st.text_input("어떻게 알았나", placeholder="예: CCTV를 직접 봄")
            if st.form_submit_button("정보 추가"):
                if fact.strip():
                    data["knowledge"].append({
                        "person": person,
                        "fact": fact.strip(),
                        "learned_episode": int(learned_ep),
                        "source": source,
                    })
                    save_data(data)
                    st.rerun()
    else:
        st.info("먼저 인물을 추가하세요.")

    for i, k in enumerate(data["knowledge"]):
        c1, c2 = st.columns([7, 1])
        c1.write(
            f"**{k.get('person')}** · {k.get('learned_episode')}화부터 앎 — "
            f"{k.get('fact')} · 근거: {k.get('source','')}"
        )
        if c2.button("삭제", key=f"delk_{i}"):
            data["knowledge"].pop(i)
            save_data(data)
            st.rerun()

# 7. 전체 설계
with tabs[8]:
    st.subheader("🗺️ 전체 시즌 설계")
    if data.get("concept_lab", {}).get("locked", False):
        st.success("정제된 최종 Canon 기반 Story Bible을 사용합니다. 검증·수정 이력은 집필 기준에서 제외됩니다.")
    total = int(data["meta"].get("episode_count", 10) or 10)
    st.caption(
        f"먼저 {total}부작 전체의 사건·반전·떡밥·클리프행어를 고정합니다. "
        "그 다음 회차 집필이 이 설계를 따라갑니다."
    )

    design_notes = st.text_area(
        "전체 설계에 추가로 반영할 지시",
        placeholder="예: 5화에서 중간 반전, 9화에서 진범 공개, 10화에서 최종 반전. "
                    "매 화 마지막 5~10초는 강한 훅."
    )

    if st.button("🧠 전체 시즌 자동 설계", type="primary", use_container_width=True):
        if not api_key:
            st.error("사이드바에 OpenAI API Key를 입력하세요.")
        elif not data.get("concept_lab", {}).get("locked", False):
            st.error("먼저 '기획 검증실'에서 기획을 재검증하고 🔒 설정을 확정하세요.")
        elif not data["meta"].get("premise", "").strip():
            st.error("먼저 '작품' 탭에서 기본 설정/로그라인을 입력하세요.")
        elif not data["meta"].get("final_truth", "").strip():
            st.error("먼저 '작품' 탭에서 작가만 아는 최종 진실을 입력하세요.")
        else:
            ctx = compact_context(data)
            with st.status("수석 작가가 전체 시즌을 설계하고 있습니다.", expanded=True) as status:
                raw = call_model(
                    api_key,
                    model,
                    """당신은 한국 숏폼 드라마의 쇼러너다.
전체 시즌을 먼저 역산 설계한다.
최종 진실은 절대 바꾸지 않는다.
반전은 앞선 단서로 공정하게 준비되어야 한다.
각 회차는 다음 화를 누르게 만드는 클리프행어로 끝난다.
인물이 모르는 사실을 아는 것처럼 행동시키지 않는다.
출력은 설명 없이 오직 유효한 JSON 배열만 반환한다.""",
                    f"""{ctx}

추가 지시:
{design_notes}

총 {total}화를 설계하라.
정확히 {total}개의 객체를 가진 JSON 배열로 출력하라.
각 객체 형식:
{{
  "number": 1,
  "title": "회차 제목",
  "objective": "이 화의 핵심 사건",
  "opening_hook": "첫 3~5초 훅",
  "beats": ["비트1", "비트2", "비트3"],
  "reveal": "이번 화에서 시청자에게 공개할 정보",
  "plant": ["이번 화에 심을 떡밥"],
  "payoff": ["이번 화에서 회수할 떡밥"],
  "knowledge_changes": ["인물: 새로 알게 되는 사실"],
  "cliffhanger": "마지막 장면",
  "must_not_reveal": "아직 공개하면 안 되는 진실"
}}

1화부터 {total}화까지 번호를 빠짐없이 사용하라.
최종화에서는 핵심 미스터리와 주요 떡밥을 회수하되 후일담용 작은 여지는 허용한다."""
                )
                try:
                    plan = extract_json(raw)
                    if not isinstance(plan, list):
                        raise ValueError("시즌 설계가 배열 형식이 아닙니다.")
                    plan = [x for x in plan if isinstance(x, dict)]
                    plan.sort(key=lambda x: int(x.get("number", 0) or 0))
                    if len(plan) != total:
                        st.warning(
                            f"AI가 {total}화가 아닌 {len(plan)}개 회차를 반환했습니다. "
                            "내용을 확인한 뒤 필요하면 다시 설계하세요."
                        )
                    data["season_plan"] = plan
                    data["season_repair_round"] = 0
                    data["season_repair_history"] = []
                    data["season_audit"] = ""
                    data["season_locked"] = False
                    save_data(data)
                    status.update(label="전체 시즌 설계 완료", state="complete")
                    st.success("전체 시즌 설계를 저장했습니다.")
                except Exception as e:
                    status.update(label="설계 결과를 저장하지 못했습니다.", state="error")
                    st.error(f"JSON 처리 오류: {e}")
                    with st.expander("AI 원문 보기"):
                        st.write(raw)

    if data["season_plan"]:
        st.divider()
        for p in sorted(data["season_plan"], key=lambda x: x.get("number", 0)):
            with st.expander(
                f"{p.get('number')}화 · {p.get('title','')} · {p.get('objective','')[:45]}"
            ):
                st.write(f"**오프닝 훅:** {p.get('opening_hook','')}")
                st.write("**핵심 비트**")
                for b in p.get("beats", []):
                    st.write(f"- {b}")
                st.write(f"**공개:** {p.get('reveal','')}")
                st.write(f"**심기:** {', '.join(p.get('plant', [])) if isinstance(p.get('plant'), list) else p.get('plant','')}")
                st.write(f"**회수:** {', '.join(p.get('payoff', [])) if isinstance(p.get('payoff'), list) else p.get('payoff','')}")
                st.write(f"**정보 변화:** {', '.join(p.get('knowledge_changes', [])) if isinstance(p.get('knowledge_changes'), list) else p.get('knowledge_changes','')}")
                st.write(f"**클리프행어:** {p.get('cliffhanger','')}")
                st.write(f"**아직 공개 금지:** {p.get('must_not_reveal','')}")


    if data["season_plan"]:
        st.divider()
        st.markdown("### 🧪 시즌 전체 시뮬레이션")
        st.caption("대본 집필 전에 1~마지막 화를 사건 상태로 시뮬레이션해 정보·인과·떡밥 충돌을 검사합니다.")
        if st.button("시즌 구조 검증", use_container_width=True):
            ctx = compact_context(data, last_episode_count=0)
            data["season_audit"] = call_model(
                api_key, model,
                """당신은 시즌 전체 continuity 시뮬레이터다.
각 화를 순서대로 실행한다고 가정해 상태 변화를 추적한다.
칭찬하지 말고 모순을 찾는다. 확정 Story Bible은 변경할 수 없는 사실이다.""",
                f"""{ctx}

1화부터 마지막 화까지 순서대로 시뮬레이션하여 검사:
- 원인 없는 결과
- 인물이 알기 전에 사용하는 정보
- 이미 안 사실을 다시 처음 아는 장면
- 심지 않은 떡밥의 회수
- 회수 예정인데 사라진 떡밥
- 최종 반전의 사전 단서 부족
- 잠금 Story Bible과 충돌
- 시간/이동/나이 모순
- 인물의 합리적인 대안 행동을 무시한 억지 전개

마지막 줄은 반드시 VERDICT: PASS 또는 VERDICT: REVISE."""
            )
            data["season_locked"] = False
            save_data(data)
            st.rerun()

        if data.get("season_audit"):
            st.write(data["season_audit"])
            if "VERDICT: PASS" in data["season_audit"].upper():
                if st.button("🔒 시즌 구조 확정", type="primary", use_container_width=True):
                    data["season_locked"] = True
                    save_data(data)
                    st.success("시즌 구조가 잠겼습니다. 이제 회차 집필이 가능합니다.")
            else:
                st.warning("시즌 구조에 수정이 필요합니다.")

                max_repairs = 5
                repair_round = int(data.get("season_repair_round", 0) or 0)
                st.caption(f"국소 보완 {repair_round}/{max_repairs}회 · 잠금 Canon 및 통과 구조 보존 모드")

                if repair_round < max_repairs and st.button(
                    "🔧 지적사항만 자동 보완 → 재검증",
                    type="primary",
                    use_container_width=True,
                    key="season_local_repair"
                ):
                    if not api_key:
                        st.error("사이드바에 OpenAI API Key를 입력하세요.")
                    else:
                        before_plan = json.loads(json.dumps(data["season_plan"], ensure_ascii=False))
                        audit_before = data["season_audit"]
                        ctx = compact_context(data, last_episode_count=0)

                        before_struct = {
                            "characters": json.loads(json.dumps(data.get("characters", []), ensure_ascii=False)),
                            "relationships": json.loads(json.dumps(data.get("relationships", []), ensure_ascii=False)),
                            "timeline": json.loads(json.dumps(data.get("timeline", []), ensure_ascii=False)),
                            "foreshadowing": json.loads(json.dumps(data.get("foreshadowing", []), ensure_ascii=False)),
                            "knowledge": json.loads(json.dumps(data.get("knowledge", []), ensure_ascii=False)),
                        }

                        with st.status("구조 오류와 서사 오류를 분리해 보정하고 있습니다.", expanded=True) as status:
                            raw_patch = ""
                            narrative_guard = ""
                            try:
                                issue_raw = call_model(
                                    api_key, model,
                                    """당신은 시즌 연속성 감사 보고서를 구조화하는 편집자다.
잠금 Canon은 수정 대상이 아니다. 실제 REVISE 원인만 원자 단위로 분해하고 같은 원인의 반복은 합친다.
문제가 인물표/나이/known_by/스키마 같은 데이터 구조 오류인지, 회차 인과/정보 습득/동기/장면 연결 같은 서사 오류인지 구분할 수 있게 target_fields를 정확히 적는다.
출력은 설명 없이 유효한 JSON 객체 하나만 반환한다.""",
                                    f"""# 잠금 Canon/Story Bible
{data.get('concept_lab', {}).get('locked_bible', '')}

# 현재 시즌 감사 보고서
{audit_before}

출력 형식:
{{
  "issues": [
    {{"id":"I1", "problem":"문제", "episodes":[1,2], "target_fields":["beats"], "required_fix":"Canon을 바꾸지 않는 최소 수정 목표"}}
  ]
}}"""
                                )
                                issue_obj = extract_json(issue_raw)
                                issues = issue_obj.get("issues", []) if isinstance(issue_obj, dict) else []
                                issues = [x for x in issues if isinstance(x, dict) and x.get("problem")]
                                if not issues:
                                    raise ValueError("감사 지적을 구조화하지 못했습니다.")

                                structural_issues, narrative_issues = split_repair_issues(issues)
                                status.write(f"총 {len(issues)}개: 구조 {len(structural_issues)}개 / 서사 {len(narrative_issues)}개로 분리했습니다.")

                                # 1단계: 명백한 스키마 오류는 AI가 아니라 코드가 직접 보정한다.
                                deterministic_changes = deterministic_repair_project_data(data)
                                if deterministic_changes:
                                    status.write("안전 규칙으로 구조 오류를 직접 보정했습니다: " + ", ".join(deterministic_changes[:8]))

                                # 구조 오류 중 Canon 의미 판단이 필요한 것은 별도의 좁은 AI 패치로 처리한다.
                                structure_ai_changes = []
                                if structural_issues:
                                    structure_raw = call_model(
                                        api_key, model,
                                        """당신은 Story Bible 구조 데이터 교정자다.
잠금 Canon에 명시된 사실만 근거로 현재 구조 데이터의 잘못된 값만 교정한다.
새 인물/새 관계/새 친자/새 사망/새 반전을 만들지 않는다.
확실하지 않은 age/birth_year는 null로 둔다. Canon에 없는 세부 정보는 추측하지 않는다.
전체 배열을 다시 만들지 말고 기존 행의 기존 필드에 대한 patch만 반환한다.
출력은 유효한 JSON 객체 하나만 반환한다.""",
                                        f"""# 잠금 Canon
{data.get('concept_lab', {}).get('locked_bible', '')}

# 구조 지적
{json.dumps(structural_issues, ensure_ascii=False, indent=2)}

# 현재 구조 데이터
characters={json.dumps(data.get('characters', []), ensure_ascii=False)}
relationships={json.dumps(data.get('relationships', []), ensure_ascii=False)}
timeline={json.dumps(data.get('timeline', []), ensure_ascii=False)}
knowledge={json.dumps(data.get('knowledge', []), ensure_ascii=False)}
foreshadowing={json.dumps(data.get('foreshadowing', []), ensure_ascii=False)}

출력:
{{"edits":[{{"table":"characters|relationships|timeline|knowledge|foreshadowing","index":0,"field":"기존필드","value":null,"reason":"Canon 근거"}}]}}"""
                                    )
                                    sobj = extract_json(structure_raw)
                                    sedits = sobj.get("edits", []) if isinstance(sobj, dict) else []
                                    tables = {"characters", "relationships", "timeline", "knowledge", "foreshadowing"}
                                    for ed in sedits if isinstance(sedits, list) else []:
                                        if not isinstance(ed, dict):
                                            continue
                                        table = str(ed.get("table", ""))
                                        idx = ed.get("index")
                                        field = str(ed.get("field", ""))
                                        if table not in tables or not isinstance(idx, int):
                                            continue
                                        rows = data.get(table, [])
                                        if idx < 0 or idx >= len(rows) or not isinstance(rows[idx], dict):
                                            continue
                                        if field not in rows[idx] or field in {"number"}:
                                            continue
                                        old = rows[idx].get(field)
                                        newv = ed.get("value")
                                        if old != newv:
                                            rows[idx][field] = newv
                                            structure_ai_changes.append(f"{table}[{idx}].{field}")
                                    if structure_ai_changes:
                                        status.write("Canon 기준 구조 패치: " + ", ".join(structure_ai_changes[:10]))

                                # 2단계: 서사 지적만 회차 필드 패치로 보낸다.
                                narrative_applied = False
                                changed_episodes = set()
                                changed_fields = []
                                candidate = json.loads(json.dumps(before_plan, ensure_ascii=False))
                                patch = {"change_summary": []}

                                if narrative_issues:
                                    ctx_after_struct = compact_context(data, last_episode_count=0)
                                    raw_patch = call_model(
                                        api_key, model,
                                        """당신은 드라마 시즌 설계의 초미세 패치 담당자다.
잠금 Story Bible/Canon은 절대 수정하지 않는다. 시즌 전체를 다시 쓰지 않는다.
이미 해결된 구조 문제를 다시 건드리지 말고, 제공된 서사 지적만 기존 회차의 기존 필드에 패치한다.
새 인물·새 사망·새 친자관계·새 범인·새 핵심 반전을 추가하지 않는다.
외부 확인 필요 전문 사실은 단정하지 않는다. 출력은 JSON 객체 하나만 반환한다.""",
                                        f"""{ctx_after_struct}

# 이번에 해결할 서사 지적
{json.dumps(narrative_issues, ensure_ascii=False, indent=2)}

# 이전 보완에서 해결된 문제(근거 없이 되살리지 말 것)
{json.dumps(data.get('season_repair_resolved', []), ensure_ascii=False, indent=2)}

출력 형식:
{{
  "edits": [{{"issue_id":"I1", "episode":1, "field":"beats", "value":[], "reason":"최소 변경 이유"}}],
  "change_summary":["I1 → 수정 → 이유"],
  "canon_guard":"Canon 변경 없음"
}}"""
                                    )
                                    patch = extract_json(raw_patch)
                                    edits = patch.get("edits", []) if isinstance(patch, dict) else []
                                    if not isinstance(edits, list) or not edits:
                                        raise ValueError("서사 보완 결과에 적용 가능한 edits가 없습니다.")

                                    by_no = {int(ep.get("number", 0) or 0): ep for ep in candidate if isinstance(ep, dict)}
                                    issue_ids = {str(x.get("id")) for x in narrative_issues}
                                    for edit in edits:
                                        if not isinstance(edit, dict):
                                            continue
                                        issue_id = str(edit.get("issue_id", ""))
                                        ep_no = int(edit.get("episode", 0) or 0)
                                        field = str(edit.get("field", "")).strip()
                                        if issue_id not in issue_ids:
                                            continue
                                        if ep_no not in by_no or field in {"number"} or field not in by_no[ep_no]:
                                            continue
                                        old_value = by_no[ep_no].get(field)
                                        new_value = edit.get("value")
                                        if isinstance(old_value, list) and not isinstance(new_value, list):
                                            continue
                                        if isinstance(old_value, dict) and not isinstance(new_value, dict):
                                            continue
                                        if old_value != new_value:
                                            by_no[ep_no][field] = new_value
                                            changed_episodes.add(ep_no)
                                            changed_fields.append(f"{ep_no}화.{field}")

                                    if changed_fields:
                                        narrative_guard = call_model(
                                            api_key, model,
                                            """당신은 Canon 변경 방지 감사관이다.
수정된 회차 필드만 보고 잠금 Canon의 관계/핵심 진실/최종 반전/결말이 바뀌었는지 검사한다.
원인-결과 연결, 정보 습득 장면, 기존 단서 명료화, 동기와 생활 연속성 보강은 허용한다.
새 인물·새 사망·새 친자관계·새 범인·새 핵심 반전 또는 외부 확인 사실의 확정은 거부한다.
마지막 줄은 GUARD: PASS 또는 GUARD: REJECT.""",
                                            f"""# 잠금 Canon
{data.get('concept_lab', {}).get('locked_bible', '')}

# 서사 지적
{json.dumps(narrative_issues, ensure_ascii=False, indent=2)}

# 변경 필드
{json.dumps(edits, ensure_ascii=False, indent=2)}"""
                                        )
                                        if "GUARD: PASS" in narrative_guard.upper():
                                            data["season_plan"] = candidate
                                            narrative_applied = True
                                            status.write("서사 패치가 Canon 보호 검사를 통과했습니다: " + ", ".join(changed_fields[:10]))
                                        else:
                                            # 2.8.3: 서사 패치만 버리고 안전한 구조 보정은 보존한다.
                                            data["season_plan"] = before_plan
                                            changed_episodes.clear()
                                            changed_fields.clear()
                                            data["season_last_repair_rejection"] = {
                                                "at": datetime.now().isoformat(timespec="seconds"),
                                                "first_guard": narrative_guard,
                                                "second_guard": "2.8.3은 거부된 서사 패치만 폐기하고 안전한 구조 보정은 유지합니다."
                                            }
                                            status.write("서사 패치는 거부됐지만 안전한 구조 보정은 유지합니다.")

                                any_change = bool(deterministic_changes or structure_ai_changes or narrative_applied)
                                if not any_change:
                                    raise ValueError("안전하게 채택할 수 있는 실제 변경이 없습니다.")

                                # 현재 데이터만으로 독립 재검증한다.
                                rectx = compact_context(data, last_episode_count=0)
                                reaudit = call_model(
                                    api_key, model,
                                    """당신은 시즌 전체 continuity 시뮬레이터다.
현재 데이터만 기준으로 1화부터 순서대로 검사한다. 잠금 Story Bible은 변경 불가다.
직전 감사 문구를 반복하지 말고 실제로 남은 문제만 보고한다.
이전 보완에서 해결된 문제는 현재 데이터에 구체적 모순이 다시 생겼을 때만 재지적한다.
데이터 구조의 null은 '미확정'이지 오류가 아니다. 외부 확인 필요 항목은 법률효과를 단정했을 때만 문제로 본다.
마지막 줄은 VERDICT: PASS 또는 VERDICT: REVISE.""",
                                    f"""{rectx}

# 직전 문제
{json.dumps(issues, ensure_ascii=False, indent=2)}

# 이번 안전 규칙 보정
{json.dumps(deterministic_changes + structure_ai_changes, ensure_ascii=False)}

# 이번 서사 변경
{json.dumps(changed_fields, ensure_ascii=False)}

# 이전에 해결된 문제
{json.dumps(data.get('season_repair_resolved', []), ensure_ascii=False, indent=2)}

검사 항목: 원인 없는 결과, 정보 선후관계, 중복 발견, 떡밥 심기·회수, 반전 단서, Canon 충돌, 시간·이동·나이 모순, 합리적 대안 행동, 외부 확인 사실의 과도한 단정.
남은 문제만 번호로 쓰고 근거 회차/데이터를 적어라."""
                                )

                                before_count = count_audit_items(audit_before)
                                after_count = count_audit_items(reaudit)
                                # 해결된 것으로 추정되는 문제를 저장하되, 재검증이 구체적으로 되살릴 수는 있다.
                                if after_count < before_count:
                                    resolved = data.setdefault("season_repair_resolved", [])
                                    summary = f"{repair_round + 1}차 보완: 문제 수 {before_count}→{after_count}"
                                    if summary not in resolved:
                                        resolved.append(summary)

                                data["season_repair_round"] = repair_round + 1
                                data["season_repair_engine_version"] = "2.8.3"
                                data.setdefault("season_repair_history", []).append({
                                    "engine": "2.8.3",
                                    "round": repair_round + 1,
                                    "at": datetime.now().isoformat(timespec="seconds"),
                                    "audit_before": audit_before,
                                    "issues": issues,
                                    "structural_issues": structural_issues,
                                    "narrative_issues": narrative_issues,
                                    "deterministic_changes": deterministic_changes,
                                    "structure_ai_changes": structure_ai_changes,
                                    "changed_episodes": sorted(changed_episodes),
                                    "changed_fields": changed_fields,
                                    "change_summary": patch.get("change_summary", []) if isinstance(patch, dict) else [],
                                    "guard": narrative_guard,
                                    "audit_after": reaudit,
                                    "before_count": before_count,
                                    "after_count": after_count,
                                    "before_plan": before_plan,
                                    "after_plan": json.loads(json.dumps(data.get("season_plan", []), ensure_ascii=False))
                                })
                                data["season_audit"] = reaudit
                                data["season_locked"] = False
                                save_data(data)
                                status.update(label=f"하이브리드 보완 완료 · 문제 수 {before_count}→{after_count}", state="complete")
                                st.rerun()
                            except Exception as e:
                                # 실패 시 시즌 설계는 복구하되, 이번 시도에서만 생긴 구조 변경도 원복한다.
                                data["season_plan"] = before_plan
                                for key, value in before_struct.items():
                                    data[key] = value
                                save_data(data)
                                status.update(label="안전하게 채택할 보완이 없어 원상복구했습니다.", state="error")
                                st.error(f"보완 실패: {e}")
                                if raw_patch:
                                    with st.expander("보완 AI 원문 보기"):
                                        st.write(raw_patch)
                elif repair_round >= max_repairs:
                    st.error("자동 국소 보완 5회를 모두 사용했습니다. 남은 문제는 직접 확인한 뒤 시즌 설계를 수정하세요.")

        if data.get("season_last_repair_rejection"):
            with st.expander("⚠️ 최근 국소 보완 거부 사유 보기"):
                rej = data.get("season_last_repair_rejection", {})
                st.caption(rej.get("at", ""))
                if rej.get("first_guard"):
                    st.markdown("**1차 Canon 보호 검사**")
                    st.write(rej.get("first_guard"))
                if rej.get("second_guard"):
                    st.markdown("**2차 Canon 보호 검사**")
                    st.write(rej.get("second_guard"))

        if data.get("season_repair_history"):
            with st.expander("🧾 시즌 보완 이력 보기"):
                for h in reversed(data["season_repair_history"]):
                    st.markdown(f"**{h.get('round')}차 보완 · {h.get('at','')}**")
                    changed = h.get("changed_episodes", [])
                    st.write(f"수정 회차: {', '.join(map(str, changed)) if changed else 'AI 보고 없음'}")
                    if h.get("changed_fields"):
                        st.write(f"잠금 해제된 필드: {', '.join(h.get('changed_fields', []))}")
                    for item in h.get("change_summary", []):
                        st.write(f"- {item}")
                    with st.expander(f"{h.get('round')}차 재검증 결과"):
                        st.write(h.get("audit_after", ""))

# 8. 회차 집필
with tabs[9]:
    st.subheader("✍️ AI 회차 집필 파이프라인")

    total = int(data["meta"].get("episode_count", 10) or 10)
    next_ep = data["episodes"][-1]["number"] + 1 if data["episodes"] else 1
    next_ep = min(max(1, next_ep), total)

    ep_no = st.number_input(
        "회차",
        min_value=1,
        max_value=total,
        value=next_ep
    )

    fixed_plan = next(
        (p for p in data["season_plan"] if p.get("number") == int(ep_no)),
        None
    )
    if fixed_plan:
        st.info(
            f"전체 설계: {fixed_plan.get('objective','')}  |  "
            f"클리프행어: {fixed_plan.get('cliffhanger','')}"
        )
    else:
        st.warning("이 회차의 전체 설계가 없습니다. 가능하면 먼저 '전체 설계'를 실행하세요.")

    extra = st.text_area(
        "이번 화에 추가할 지시 (선택)",
        placeholder="전체 설계를 바꾸지 않는 범위에서 추가할 연출/대사/장면 지시"
    )

    st.caption(
        "실행 순서: 회차 설계 → 초고 → 연속성 감사 → 최종 수정 → "
        "인물 정보 변화 추출"
    )

    if st.button("🎬 이번 화 완성하기", type="primary", use_container_width=True):
        if not api_key:
            st.error("사이드바에 OpenAI API Key를 입력하세요.")
        elif not data.get("season_locked", False):
            st.error("먼저 '전체 설계'에서 시즌 구조를 검증하고 🔒 확정하세요.")
        else:
            ctx = compact_context(data, current_episode=int(ep_no))
            with st.status("AI 작가실 가동 중", expanded=True) as status:
                st.write("1/5 구성 작가: 전체 설계를 촬영 가능한 비트로 구체화")
                outline = call_model(
                    api_key,
                    model,
                    """당신은 한국 숏폼 드라마의 수석 구성작가다.
전체 시즌 설계와 Story Bible을 고정된 사실로 취급한다.
이번 화가 담당한 공개/떡밥/회수/클리프행어를 임의로 다음 화로 미루지 않는다.
최종 진실을 조기 노출하지 않는다.""",
                    f"""{ctx}

대상: {int(ep_no)}화
사용자 추가 지시: {extra}

60~120초 기준으로 오프닝 훅, 4~7개 비트, 감정 전환,
정보 공개 시점, 떡밥 심기/회수, 마지막 클리프행어를 구체화하라."""
                )

                st.write("2/5 대본 작가: 촬영 가능한 초고 작성")
                draft = call_model(
                    api_key,
                    model,
                    """당신은 한국 숏폼 드라마 전문 대본작가다.
대사는 짧고 실제 배우가 말할 수 있어야 한다.
설명 대사를 남발하지 말고 행동과 충돌로 보여준다.
주어진 바이블과 전체 시즌 설계를 절대 임의 변경하지 않는다.
등장인물은 현재 자신이 아는 정보만 사용한다.""",
                    f"""{ctx}

{int(ep_no)}화 상세 구성:
{outline}

촬영 가능한 완성 대본 초고를 작성하라.
장면표기, 행동, 대사를 포함하고 60~120초 분량으로 압축하라."""
                )

                st.write("3/7 대사 전문작가: 대사의 맛과 감정 충돌 강화")
                dialogue = call_model(api_key, model, "당신은 한국 숏폼 드라마의 대사 전문작가다. 사건과 확정 설정은 바꾸지 않는다. 설명 대사를 줄이고 인물별 말투, 숨은 의도, 감정 충돌, 기억에 남는 짧은 대사를 강화한다. 새로운 비밀이나 반전을 추가하지 않는다.", f"{ctx}\n\n구성:\n{outline}\n\n초고:\n{draft}\n\n같은 사건 순서와 정보 공개 시점을 유지하면서 대사와 행동만 더 날카롭게 다듬은 대본을 작성하라.")
                st.write("4/7 숏폼 편집자: 첫 5초와 이탈 구간 강화")
                retention = call_model(api_key, model, "당신은 숏폼 드라마 편집자다. 확정 설정, 사건 순서, 공개 정보, 최종 클리프행어는 바꾸지 않는다. 첫 3~5초 훅을 선명하게 하고 중복 설명과 늘어지는 부분을 제거한다. 60~120초 안에서 감정 상승과 마지막 10초의 힘을 강화한다. 새 반전은 만들지 않는다.", f"{ctx}\n\n대사 강화본:\n{dialogue}\n\n촬영 가능한 최종 후보 대본으로 압축/강화하라.")
                st.write("5/7 연속성 편집자: 모순/조기 스포일러/정보 오류 검사")
                audit = call_model(
                    api_key,
                    model,
                    """당신은 드라마 continuity 전문 편집자다.
재미 평가보다 모순 검사가 우선이다.
혈연, 나이, 연표, 인물별 정보 보유 시점, 동기, 이동/시간,
전체 시즌 설계, 떡밥 심기/회수, 최종 진실과의 충돌을 검사한다.
특히 '아직 몰라야 하는 인물이 알고 말하는 오류'와
'나중 반전을 이번 화에서 실수로 노출하는 오류'를 잡는다.""",
                    f"""{ctx}

검사 대상 {int(ep_no)}화:
{retention}

치명적/중요/경미로 나누고 각 문제에 최소 수정 방법을 제시하라.
문제가 없으면 '치명적 모순 없음'이라고 명확히 적어라."""
                )

                st.write("6/7 편집장: 감사 결과를 반영한 최종본 작성")
                final = call_model(
                    api_key,
                    model,
                    """당신은 드라마 편집장이다.
감사에서 확인된 실제 오류만 고친다.
전체 시즌 설계의 핵심 사건, 공개 시점, 클리프행어를 지킨다.
새로운 설정으로 억지 해결하지 않는다.""",
                    f"""{ctx}

대사/숏폼 강화본:
{retention}

감사 보고서:
{audit}

감사를 반영한 최종 대본만 작성하라.
대본 뒤에는 별도 해설을 길게 붙이지 마라."""
                )

                st.write("7/7 스크립트 슈퍼바이저: 이번 화의 상태 변화 추출")
                state_raw = call_model(
                    api_key,
                    model,
                    """당신은 스크립트 슈퍼바이저다.
완성 대본에서 실제로 발생한 상태 변화만 추출한다.
추측하거나 새 설정을 만들지 않는다.
출력은 설명 없이 오직 유효한 JSON 객체만 반환한다.""",
                    f"""{ctx}

완성된 {int(ep_no)}화:
{final}

다음 형식의 JSON 객체로만 출력:
{{
  "new_facts": ["이번 화에서 새로 확정된 사실"],
  "knowledge_updates": [
    {{
      "person": "인물 이름",
      "fact": "이번 화에서 새로 알게 된 사실",
      "learned_episode": {int(ep_no)},
      "source": "어떻게 알았는지"
    }}
  ],
  "planted_clues": ["실제로 심어진 떡밥"],
  "paid_off_clues": ["실제로 회수된 떡밥"],
  "character_state_changes": ["관계/감정/상태 변화"]
}}"""
                )

                try:
                    state = extract_json(state_raw)
                    if not isinstance(state, dict):
                        state = {}
                except Exception:
                    state = {"raw": state_raw}

                ep = {
                    "number": int(ep_no),
                    "objective": fixed_plan.get("objective", "") if fixed_plan else extra,
                    "outline": outline,
                    "draft": draft,
                    "dialogue": dialogue,
                    "retention": retention,
                    "audit": audit,
                    "final": final,
                    "state_changes": state,
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                }

                data["episodes"] = [
                    e for e in data["episodes"]
                    if e.get("number") != int(ep_no)
                ] + [ep]
                data["episodes"].sort(key=lambda x: x.get("number", 0))

                if isinstance(state, dict):
                    upsert_knowledge(data, state.get("knowledge_updates", []))

                    paid = state.get("paid_off_clues", [])
                    if isinstance(paid, list):
                        for clue in data["foreshadowing"]:
                            if clue.get("clue") in paid:
                                clue["status"] = "회수완료"

                save_data(data)
                status.update(label="완성했습니다", state="complete")

            st.success(f"{int(ep_no)}화 저장 완료")
            st.markdown("### 최종 대본")
            st.write(final)

            with st.expander("이번 화 상태 변화"):
                st.json(state)
            with st.expander("설정 감사 보고서"):
                st.write(audit)
            with st.expander("초고 / 구성 보기"):
                st.markdown("#### 구성")
                st.write(outline)
                st.markdown("#### 초고")
                st.write(draft)
                st.markdown("#### 대사 강화")
                st.write(dialogue)
                st.markdown("#### 숏폼 강화")
                st.write(retention)

    if data["episodes"]:
        st.divider()
        st.subheader("저장된 회차")
        for ep in sorted(data["episodes"], key=lambda x: x.get("number", 0), reverse=True):
            with st.expander(f"{ep.get('number')}화 · {ep.get('objective','')[:60]}"):
                st.markdown("#### 최종본")
                st.write(ep.get("final", ""))
                st.markdown("#### 상태 변화")
                st.json(ep.get("state_changes", {}))
                st.markdown("#### 설정 감사")
                st.write(ep.get("audit", ""))

# 9. 설정 감사
with tabs[10]:
    st.subheader("🔎 설정 감사")

    st.markdown("#### 1차: 프로그램 규칙 기반 검사")
    for x in deterministic_audit(data):
        st.write(x)

    st.markdown("#### 2차: AI 전체 프로젝트 심층 감사")
    if st.button("🔎 전체 바이블 + 시즌 설계 심층 검사", use_container_width=True):
        if not api_key:
            st.error("OpenAI API Key가 필요합니다.")
        else:
            ctx = compact_context(data, last_episode_count=10)
            result = call_model(
                api_key,
                model,
                """당신은 장편 드라마 설정 감사 책임자다.
칭찬보다 오류 탐지가 우선이다.
혈연/나이/연표/직업/법적 관계/인물별 정보 보유 시점/행동 동기/
떡밥 심기와 회수/전체 시즌 설계/최종 반전의 논리성을 역산한다.
확정 설정을 임의로 새로 만들지 않는다.""",
                f"""{ctx}

출력 순서:
1) 치명적 모순
2) 정보 보유 오류
3) 떡밥 미회수/너무 이른 회수
4) 반전의 사전 단서 부족
5) 행동 동기 부족
6) 시청자가 즉시 물을 질문
7) 최소 수정 제안

문제가 없으면 해당 항목에 '없음'이라고 적어라."""
            )
            st.write(result)

st.caption("AI 드라마 작가실 2.8.3 · 구조 오류는 안전 규칙으로 직접 보정하고, 서사 오류만 AI가 필드 단위로 국소 수정합니다. · project.json 저장")
