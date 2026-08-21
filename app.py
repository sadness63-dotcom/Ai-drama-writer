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
                "season_plan", "knowledge", "episodes", "notes"]:
        if not isinstance(base.get(key), list):
            base[key] = []
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

    return f"""# 작품 바이블
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


st.set_page_config(
    page_title="AI 드라마 작가실 2.0",
    page_icon="🎬",
    layout="wide"
)

st.title("🎬 AI 드라마 작가실 2.0")
st.caption("Story Bible → 10부작 전체 설계 → 떡밥/정보 추적 → 회차 집필 → 연속성 감사")

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

# 1. 작품
with tabs[0]:
    st.subheader("작품 바이블")
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
with tabs[1]:
    st.subheader("인물 카드")
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
with tabs[2]:
    st.subheader("관계도")
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
with tabs[3]:
    st.subheader("사건 연표")
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
with tabs[4]:
    st.subheader("떡밥 추적 장부")
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
with tabs[5]:
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
with tabs[6]:
    st.subheader("🗺️ 전체 시즌 설계")
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

# 8. 회차 집필
with tabs[7]:
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

                st.write("3/5 연속성 편집자: 모순/조기 스포일러/정보 오류 검사")
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
{draft}

치명적/중요/경미로 나누고 각 문제에 최소 수정 방법을 제시하라.
문제가 없으면 '치명적 모순 없음'이라고 명확히 적어라."""
                )

                st.write("4/5 편집장: 감사 결과를 반영한 최종본 작성")
                final = call_model(
                    api_key,
                    model,
                    """당신은 드라마 편집장이다.
감사에서 확인된 실제 오류만 고친다.
전체 시즌 설계의 핵심 사건, 공개 시점, 클리프행어를 지킨다.
새로운 설정으로 억지 해결하지 않는다.""",
                    f"""{ctx}

초고:
{draft}

감사 보고서:
{audit}

감사를 반영한 최종 대본만 작성하라.
대본 뒤에는 별도 해설을 길게 붙이지 마라."""
                )

                st.write("5/5 스크립트 슈퍼바이저: 이번 화의 상태 변화 추출")
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
with tabs[8]:
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

st.caption("AI 드라마 작가실 2.0 · 프로젝트 데이터는 project.json에 저장됩니다.")
