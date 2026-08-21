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
        "format": "숏폼 20부작, 회당 2분",
        "tone": "빠르고 자극적이되, 인물 행동에는 이유가 있다.",
        "premise": "",
        "final_truth": "",
    },
    "characters": [],
    "relationships": [],
    "timeline": [],
    "foreshadowing": [],
    "episodes": [],
    "notes": [],
}


def load_data():
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULT_DATA, ensure_ascii=False))


def save_data(data):
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def slugify(text):
    text = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", text.strip())
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


def compact_context(data, last_episode_count=3):
    meta = data["meta"]
    chars = data["characters"]
    rels = data["relationships"]
    timeline = data["timeline"]
    clues = data["foreshadowing"]
    episodes = data["episodes"][-last_episode_count:]

    return f"""# 작품 핵심
제목: {meta.get('title','')}
장르: {meta.get('genre','')}
형식: {meta.get('format','')}
톤: {meta.get('tone','')}
기본 설정: {meta.get('premise','')}
작가만 아는 최종 진실: {meta.get('final_truth','')}

# 인물
{json.dumps(chars, ensure_ascii=False, indent=2)}

# 관계
{json.dumps(rels, ensure_ascii=False, indent=2)}

# 연표
{json.dumps(timeline, ensure_ascii=False, indent=2)}

# 떡밥
{json.dumps(clues, ensure_ascii=False, indent=2)}

# 최근 회차
{json.dumps(episodes, ensure_ascii=False, indent=2)}
"""


def deterministic_audit(data):
    issues = []
    chars = {c.get("name", "").strip(): c for c in data["characters"] if c.get("name", "").strip()}

    # Basic character integrity
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
                    issues.append(f"❌ {name}({age})와 {label} {p}({pa})의 나이 차가 {pa-age}세뿐입니다.")

    # Parent graph utilities
    def parents(name):
        if name not in chars:
            return set()
        c = chars[name]
        return {x for x in [str(c.get("biological_mother", "")).strip(), str(c.get("biological_father", "")).strip()] if x}

    def ancestors(name, depth=5):
        seen = set()
        frontier = {name}
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

    # Relationship integrity & blood checks
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
            pa, pb = parents(a), parents(b)
            shared = pa & pb
            if shared:
                issues.append(f"❌ 혈연 오류: {a}와 {b}는 공통 부모({', '.join(shared)})가 있는데 '{kind}' 관계입니다.")

    # Timeline chronological sanity when year values are integers
    numeric_events = [e for e in data["timeline"] if isinstance(e.get("year"), int)]
    for e in numeric_events:
        actor = str(e.get("person", "")).strip()
        if actor in chars and isinstance(chars[actor].get("birth_year"), int):
            if e["year"] < chars[actor]["birth_year"]:
                issues.append(f"❌ 연표 오류: {actor}의 사건({e['year']})이 출생연도({chars[actor]['birth_year']})보다 빠릅니다.")

    if not issues:
        issues.append("✅ 프로그램 규칙 기반 검사에서는 즉시 드러나는 혈연/나이/관계 오류를 찾지 못했습니다.")
    return issues


st.set_page_config(page_title="AI 드라마 작가실", page_icon="🎬", layout="wide")
st.title("🎬 AI 드라마 작가실")
st.caption("Story Bible → 회차 설계 → 초고 → 설정 감사 → 수정본까지 한 번에")

if "data" not in st.session_state:
    st.session_state.data = load_data()
data = st.session_state.data

with st.sidebar:
    st.header("AI 설정")
    api_key = st.text_input("OpenAI API Key", type="password", value=os.getenv("OPENAI_API_KEY", ""))
    model = st.selectbox("모델", ["gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.6"], index=0)
    st.caption("Terra: 기본 추천 · Sol: 최종 설계/검수 · Luna: 비용 절약")
    if st.button("💾 전체 저장", use_container_width=True):
        save_data(data)
        st.success("저장했습니다.")

    export_json = json.dumps(data, ensure_ascii=False, indent=2)
    st.download_button("⬇️ 프로젝트 JSON", export_json, file_name=f"{slugify(data['meta'].get('title','project'))}.json", mime="application/json", use_container_width=True)
    upload = st.file_uploader("프로젝트 JSON 불러오기", type=["json"])
    if upload is not None:
        try:
            imported = json.loads(upload.getvalue().decode("utf-8"))
            if st.button("이 프로젝트로 교체", use_container_width=True):
                st.session_state.data = imported
                save_data(imported)
                st.rerun()
        except Exception as e:
            st.error(f"JSON 오류: {e}")


tabs = st.tabs(["작품", "인물", "관계", "연표", "떡밥", "회차 집필", "설정 감사"])

with tabs[0]:
    st.subheader("작품 바이블")
    c1, c2 = st.columns(2)
    with c1:
        data["meta"]["title"] = st.text_input("제목", data["meta"].get("title", ""))
        data["meta"]["genre"] = st.text_input("장르", data["meta"].get("genre", ""))
        data["meta"]["format"] = st.text_input("형식", data["meta"].get("format", ""))
    with c2:
        data["meta"]["tone"] = st.text_area("톤 / 문체", data["meta"].get("tone", ""), height=110)
    data["meta"]["premise"] = st.text_area("기본 설정 / 로그라인", data["meta"].get("premise", ""), height=140)
    data["meta"]["final_truth"] = st.text_area("🔒 작가만 아는 최종 진실", data["meta"].get("final_truth", ""), height=180, help="최종 반전과 실제 사건의 진실. 시청자에게는 자동 공개되지 않습니다.")
    save_data(data)

with tabs[1]:
    st.subheader("인물 카드")
    with st.expander("➕ 인물 추가", expanded=not data["characters"]):
        with st.form("add_character", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("이름")
            age = c2.number_input("현재 나이", min_value=0, max_value=120, value=30)
            birth_year = c3.number_input("출생연도(모르면 0)", min_value=0, max_value=2100, value=0)
            role = st.text_input("역할", placeholder="예: 주인공 / 재벌가 회장 / 사돈")
            bio_m = st.text_input("친모 이름")
            bio_f = st.text_input("친부 이름")
            raised_by = st.text_input("양육자/양육가족")
            secret = st.text_area("숨기는 비밀")
            desire = st.text_area("욕망 / 목표")
            if st.form_submit_button("인물 추가"):
                if name.strip():
                    data["characters"].append({"name": name.strip(), "age": int(age), "birth_year": int(birth_year) if birth_year else None, "role": role, "biological_mother": bio_m.strip(), "biological_father": bio_f.strip(), "raised_by": raised_by.strip(), "secret": secret, "desire": desire})
                    save_data(data)
                    st.rerun()
    for i, c in enumerate(data["characters"]):
        with st.expander(f"{c.get('name','')} · {c.get('age','')}세 · {c.get('role','')}"):
            cols = st.columns(2)
            c["role"] = cols[0].text_input("역할", c.get("role", ""), key=f"role_{i}")
            c["age"] = int(cols[1].number_input("현재 나이", 0, 120, int(c.get("age") or 0), key=f"age_{i}"))
            c["biological_mother"] = cols[0].text_input("친모", c.get("biological_mother", ""), key=f"bm_{i}")
            c["biological_father"] = cols[1].text_input("친부", c.get("biological_father", ""), key=f"bf_{i}")
            c["raised_by"] = st.text_input("양육자/양육가족", c.get("raised_by", ""), key=f"rb_{i}")
            c["secret"] = st.text_area("비밀", c.get("secret", ""), key=f"secret_{i}")
            c["desire"] = st.text_area("욕망/목표", c.get("desire", ""), key=f"desire_{i}")
            if st.button("이 인물 삭제", key=f"delc_{i}"):
                data["characters"].pop(i)
                save_data(data)
                st.rerun()
    save_data(data)

with tabs[2]:
    st.subheader("관계도")
    names = [c.get("name", "") for c in data["characters"] if c.get("name")]
    if len(names) >= 2:
        with st.form("add_rel", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            a = c1.selectbox("인물 A", names)
            b = c2.selectbox("인물 B", names, index=1 if len(names)>1 else 0)
            typ = c3.selectbox("관계", ["부부", "연인", "약혼", "친구", "원수", "사돈", "직장", "의붓부모-자녀", "기타"])
            detail = st.text_input("관계 설명")
            if st.form_submit_button("관계 추가"):
                data["relationships"].append({"a": a, "b": b, "type": typ, "detail": detail})
                save_data(data)
                st.rerun()
    else:
        st.info("인물을 2명 이상 추가하세요.")
    for i, r in enumerate(data["relationships"]):
        c1, c2 = st.columns([6,1])
        c1.write(f"**{r.get('a')} ↔ {r.get('b')}** · {r.get('type')} · {r.get('detail','')}")
        if c2.button("삭제", key=f"delr_{i}"):
            data["relationships"].pop(i); save_data(data); st.rerun()

with tabs[3]:
    st.subheader("사건 연표")
    with st.form("timeline", clear_on_submit=True):
        c1, c2 = st.columns([1,3])
        year_text = c1.text_input("연도/시점", placeholder="2001 또는 25년 전")
        event = c2.text_input("사건")
        person = st.text_input("관련 인물")
        knowledge = st.text_input("이 사건을 현재 알고 있는 인물")
        if st.form_submit_button("연표 추가"):
            year = int(year_text) if year_text.strip().isdigit() else year_text.strip()
            data["timeline"].append({"year": year, "event": event, "person": person, "known_by": knowledge})
            save_data(data); st.rerun()
    for i, e in enumerate(data["timeline"]):
        c1, c2 = st.columns([7,1])
        c1.write(f"**{e.get('year')}** — {e.get('event')}  · 관련: {e.get('person','')} · 알고 있음: {e.get('known_by','')}")
        if c2.button("삭제", key=f"delt_{i}"):
            data["timeline"].pop(i); save_data(data); st.rerun()

with tabs[4]:
    st.subheader("떡밥 관리")
    with st.form("clue", clear_on_submit=True):
        clue = st.text_input("떡밥")
        planted = st.number_input("심는 화", min_value=1, value=1)
        payoff = st.number_input("회수 예정 화", min_value=1, value=5)
        truth = st.text_area("실제 의미 / 정답")
        if st.form_submit_button("떡밥 추가"):
            data["foreshadowing"].append({"clue": clue, "planted_episode": int(planted), "payoff_episode": int(payoff), "truth": truth, "status": "미회수"})
            save_data(data); st.rerun()
    for i, f in enumerate(data["foreshadowing"]):
        c1, c2, c3 = st.columns([5,2,1])
        c1.write(f"**{f.get('clue')}** · {f.get('planted_episode')}화 → {f.get('payoff_episode')}화 · {f.get('truth','')}")
        f["status"] = c2.selectbox("상태", ["미회수", "부분회수", "회수완료"], index=["미회수", "부분회수", "회수완료"].index(f.get("status", "미회수")), key=f"status_{i}")
        if c3.button("삭제", key=f"delf_{i}"):
            data["foreshadowing"].pop(i); save_data(data); st.rerun()
    save_data(data)

with tabs[5]:
    st.subheader("AI 회차 집필 파이프라인")
    ep_no = st.number_input("회차", min_value=1, max_value=1000, value=(data["episodes"][-1]["number"] + 1 if data["episodes"] else 1))
    objective = st.text_area("이번 화에서 반드시 일어나야 할 일", placeholder="예: 결혼식장에서 두 사돈이 처음 재회한다. 마지막 10초에 지연이 혜숙을 알아본다.")
    st.caption("한 번 실행하면: 회차 설계 → 초고 → 설정 감사 → 수정본 순서로 AI를 사용합니다.")

    if st.button("🎬 이번 화 완성하기", type="primary", use_container_width=True):
        if not api_key:
            st.error("사이드바에 OpenAI API Key를 입력하세요.")
        elif not objective.strip():
            st.error("이번 화 목표를 적어주세요.")
        else:
            ctx = compact_context(data)
            with st.status("작가실 가동 중", expanded=True) as status:
                st.write("1/4 구성 작가가 회차 비트를 설계합니다.")
                outline = call_model(api_key, model,
                    "당신은 한국 숏폼 막장 드라마의 수석 구성작가다. 자극성보다 먼저 인과관계와 인물 동기를 지킨다. 제공된 최종 진실과 설정을 절대 임의로 바꾸지 않는다.",
                    f"{ctx}\n\n이번 화: {int(ep_no)}화\n필수 사건: {objective}\n\n60~120초 숏폼 기준으로 오프닝 훅, 4~7개 비트, 정보 공개, 감정 전환, 마지막 클리프행어를 설계하라. 기존 떡밥 중 이번 화에서 심거나 회수할 것을 명시하라.")

                st.write("2/4 대본 작가가 초고를 씁니다.")
                draft = call_model(api_key, model,
                    "당신은 한국 막장 숏폼 드라마 전문 대본작가다. 대사는 짧고 실제 배우가 말할 수 있게 쓴다. 설명 대사를 줄이고 행동과 충돌로 보여준다. 한 화의 마지막에는 강한 미해결 질문을 남긴다. 설정을 새로 만들지 말고 주어진 바이블을 따른다.",
                    f"{ctx}\n\n회차 설계:\n{outline}\n\n{int(ep_no)}화의 촬영 가능한 완성 대본을 써라. 장면표기, 행동, 대사를 포함하되 60~120초 분량으로 압축하라.")

                st.write("3/4 설정 감사가 모순을 찾습니다.")
                audit = call_model(api_key, model,
                    "당신은 드라마 연속성(continuity) 전문 편집자다. 재미를 평가하기 전에 모순을 잡는다. 혈연, 나이, 임신 가능 시점, 결혼관계, 인물의 지식 범위, 이동/시간, 기존 떡밥, 최종 진실과의 충돌을 검사한다. 문제 없으면 문제 없다고 명확히 말한다.",
                    f"{ctx}\n\n검사 대상 {int(ep_no)}화 초고:\n{draft}\n\n오류를 치명적/중요/경미로 나누고, 각 오류마다 '왜 모순인지'와 '최소 수정 방법'을 제시하라. 새로운 설정을 만들어 해결하지 마라.")

                st.write("4/4 편집장이 오류를 반영해 최종본을 만듭니다.")
                final = call_model(api_key, model,
                    "당신은 드라마 편집장이다. 감사 보고서의 실제 오류만 고치고, 원래 회차의 재미와 클리프행어는 최대한 유지한다. Story Bible의 확정 사실을 바꾸면 안 된다.",
                    f"{ctx}\n\n초고:\n{draft}\n\n감사 보고서:\n{audit}\n\n감사를 반영한 최종 대본을 작성하라. 마지막에 [이번 화 신규 확정 사실]과 [이번 화에 남긴 떡밥]을 짧게 덧붙여라.")

                ep = {"number": int(ep_no), "objective": objective, "outline": outline, "draft": draft, "audit": audit, "final": final, "created_at": datetime.now().isoformat(timespec="seconds")}
                # replace same episode number if present
                data["episodes"] = [e for e in data["episodes"] if e.get("number") != int(ep_no)] + [ep]
                data["episodes"].sort(key=lambda x: x.get("number", 0))
                save_data(data)
                status.update(label="완성했습니다", state="complete")
            st.success(f"{int(ep_no)}화 저장 완료")
            st.markdown("### 최종 대본")
            st.write(final)
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
        for ep in sorted(data["episodes"], key=lambda x: x.get("number",0), reverse=True):
            with st.expander(f"{ep.get('number')}화 · {ep.get('objective','')[:60]}"):
                st.markdown("#### 최종본")
                st.write(ep.get("final", ""))
                st.markdown("#### 설정 감사")
                st.write(ep.get("audit", ""))

with tabs[6]:
    st.subheader("설정 감사")
    st.markdown("#### 1차: 프로그램 규칙 기반 검사")
    for x in deterministic_audit(data):
        st.write(x)

    st.markdown("#### 2차: AI 전체 설정 감사")
    if st.button("🔎 전체 바이블 심층 검사", use_container_width=True):
        if not api_key:
            st.error("OpenAI API Key가 필요합니다.")
        else:
            ctx = compact_context(data, last_episode_count=10)
            result = call_model(api_key, model,
                "당신은 장편 드라마 설정 감사 책임자다. 작가를 칭찬하지 말고 모순을 먼저 찾는다. 혈연/나이/연표/임신과 출산/결혼/상속/직업/인물별 정보 보유 시점/행동동기/떡밥 회수/최종 반전의 논리성을 역산한다.",
                f"다음 작품 바이블을 감사하라.\n\n{ctx}\n\n출력 순서: 1) 치명적 모순 2) 잠재적 모순 3) 동기 부족 4) 시청자가 즉시 물을 질문 5) 수정 제안. 확정 설정을 임의로 새로 만들지 말고, 충돌 지점과 선택지를 제시하라.")
            st.write(result)
