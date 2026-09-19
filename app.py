import json
from typing import Any

import requests
import streamlit as st

from analysis import analyze_overlap, get_api_key
from github_client import fetch_readme, get_github_token, parse_repositories, search_github_repositories
from card_selector import card_selector
from text_morph import text_morph


st.set_page_config(
    page_title="CrossTalk | Overlap detector",
    page_icon="X",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Space+Grotesk:wght@400;500;600;700&display=swap');

    :root {
        --ink: #17221f;
        --muted: #68736f;
        --paper: #f4f4ed;
        --mint: #b9e6d5;
        --orange: #f3784b;
        --line: rgba(23, 34, 31, .16);
        --orange-shadow: color-mix(in srgb, var(--orange) 65%, black);
        --mint-shadow: color-mix(in srgb, var(--mint) 65%, black);
        --ink-shadow: color-mix(in srgb, var(--ink) 55%, black);
    }

    .stApp {
        background: var(--paper);
        color: var(--ink);
    }
    .block-container {
        max-width: 1180px;
        padding: 3rem 2rem 5rem;
    }
    h1, h2, h3, p, label, button, input { font-family: 'Space Grotesk', sans-serif !important; }
    h1 { font-size: clamp(2.5rem, 6vw, 5.8rem) !important; line-height: .94 !important; letter-spacing: -0.06em !important; }
    h2 { letter-spacing: -0.04em !important; }
    .eyebrow, .mono, code { font-family: 'DM Mono', monospace !important; }
    .eyebrow { color: var(--orange); font-size: .75rem; letter-spacing: .16em; text-transform: uppercase; }
    .lede { color: var(--muted); font-size: 1.08rem; max-width: 550px; line-height: 1.55; }
    .rule { border-top: 1px solid var(--line); margin: 2.6rem 0; }
    .score-panel { background: var(--ink); color: var(--paper); padding: 1.75rem; min-height: 220px; display: flex; flex-direction: column; justify-content: space-between; border-radius: 20px 20px 0 0; }
    .score-number { font-family: 'DM Mono', monospace; font-size: clamp(3.5rem, 8vw, 6.5rem); line-height: .9; color: var(--mint); }
    .score-label { color: #aebbb5; font-family: 'DM Mono', monospace; font-size: .72rem; text-transform: uppercase; letter-spacing: .12em; }
    div.st-key-summary_panel { border: 1px solid var(--line); border-left: 6px solid var(--orange); padding: 1.5rem 1.75rem; background: rgba(255,255,255,.25); min-height: 220px; border-radius: 0 20px 20px 20px; }
    div.st-key-summary_panel h3 { margin-top: 0; }
    div[data-testid='stExpander'] { border: 1px solid var(--line); border-radius: 16px; background: rgba(255,255,255,.25); overflow: hidden; }
    div[data-testid='stTextInput'] input, div[data-testid='stTextArea'] textarea { border: 1px solid var(--line); border-radius: 14px; background: #ffffff; color: var(--ink) !important; caret-color: var(--ink); }
    div[data-testid='stTextInput'] input::placeholder, div[data-testid='stTextArea'] textarea::placeholder { color: #69756f !important; opacity: 1; }
    div[data-testid='stMultiSelect'] [data-baseweb='tag'] { background: var(--ink); color: #ffffff; }
    div[data-testid='stMultiSelect'] input { color: var(--ink) !important; }
    div[data-testid='stDataFrame'] { color: var(--ink); }
    .project-card { border: 1px solid var(--line); border-left: 5px solid var(--mint); padding: 1rem 1.25rem; margin: .65rem 0; background: #ffffff; color: var(--ink); border-radius: 4px 14px 14px 4px; }
    .project-card strong { color: var(--ink); }
    .project-meta { color: #52605a; font-size: .92rem; }
    div[data-testid='stButton'] button { border-radius: 14px; background: var(--orange); color: #fff; border: 0; padding: .7rem 1.4rem; font-weight: 700; box-shadow: 0 5px 0 var(--orange-shadow); transition: transform .12s ease, box-shadow .12s ease, background .12s ease; }
    div[data-testid='stButton'] button:hover { background: var(--orange); transform: translateY(-2px); box-shadow: 0 7px 0 var(--orange-shadow); }
    div[data-testid='stButton'] button:active { transform: translateY(3px); box-shadow: 0 2px 0 var(--orange-shadow); }
    .tag { display: inline-block; padding: .35rem .7rem; margin: .2rem .3rem .2rem 0; background: var(--mint); color: var(--ink); font-family: 'DM Mono', monospace; font-size: .72rem; border-radius: 999px; }
    .tier-badge { display: inline-block; padding: .3rem .8rem; margin-bottom: .6rem; font-family: 'DM Mono', monospace; font-size: .75rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; border: 1px solid var(--ink); border-radius: 999px; }
    .tier-s { background: var(--orange); color: #fff; border-color: var(--orange); box-shadow: 0 3px 0 var(--orange-shadow); }
    .tier-a { background: var(--mint); color: var(--ink); box-shadow: 0 3px 0 var(--mint-shadow); }
    .tier-solid { background: transparent; color: var(--ink); }
    .tier-competing { background: transparent; color: var(--muted); border-color: var(--line); }
    .rank-badge { display: inline-block; padding: .3rem .7rem; margin: 0 .5rem .6rem 0; font-family: 'DM Mono', monospace; font-size: .75rem; font-weight: 700; border-radius: 999px; background: var(--paper); border: 1px solid var(--line); color: var(--ink); }
    .rank-1 { background: #ffd868; border-color: #d9a900; box-shadow: 0 3px 0 #b98600; }
    .rank-2 { background: #e3e3e3; border-color: #aaaaaa; box-shadow: 0 3px 0 #8c8c8c; }
    .rank-3 { background: #e8b487; border-color: #a56a34; box-shadow: 0 3px 0 #8a5527; }
    .streak-chip { display: inline-block; padding: .5rem 1.1rem; margin: .75rem 0 0; background: var(--orange); color: #fff; border-radius: 999px; font-family: 'DM Mono', monospace; font-weight: 700; font-size: .85rem; box-shadow: 0 4px 0 var(--orange-shadow); }
    .meter { margin: .35rem 0 .9rem; }
    .meter-label-row { display: flex; justify-content: space-between; font-family: 'DM Mono', monospace; font-size: .7rem; text-transform: uppercase; letter-spacing: .08em; font-weight: 700; margin-bottom: .3rem; }
    .meter-label-dark { color: #aebbb5; }
    .meter-label-light { color: var(--muted); }
    .meter-track { background: rgba(23, 34, 31, .08); border-radius: 999px; height: 14px; overflow: hidden; }
    .meter-track.on-dark { background: rgba(255, 255, 255, .18); }
    .meter-fill { height: 100%; border-radius: 999px; transition: width .6s cubic-bezier(.22, 1, .36, 1); }
    .meter-fill-composability { background: linear-gradient(90deg, var(--mint), color-mix(in srgb, var(--mint) 55%, var(--ink))); }
    .meter-fill-redundancy { background: linear-gradient(90deg, var(--orange), color-mix(in srgb, var(--orange) 60%, var(--ink))); }
    div.st-key-repo_input label p { color: #000; }
    /* text_morph.py mounts as its own Streamlit element, so it lands as a sibling right
       after the score-panel div rather than nested inside it (each st.markdown call is its
       own HTML fragment). Style it here to read as a visual continuation of that panel. */
    div.st-key-score_text_morph { margin-top: -1rem; }
    div.st-key-score_text_morph .stBidiComponent { display: block; background: var(--ink); padding: 0 1.75rem 1.5rem; border-radius: 0 0 20px 20px; }
    </style>
    """,
    unsafe_allow_html=True,
)


DEFAULT_REPOS = ""
TIER_CSS_CLASSES = {
    "S-TIER MATCH": "tier-s",
    "A-TIER MATCH": "tier-a",
    "SOLID MATCH": "tier-solid",
    "COMPETING": "tier-competing",
}
RANK_MEDAL_CLASSES = {1: "rank-1", 2: "rank-2", 3: "rank-3"}


def meter_bar_html(score: int, label: str, variant: str, on_dark: bool = False) -> str:
    """A hand-rolled HUD-style meter bar (avoids fighting st.progress's default styling)."""
    track_class = "meter-track on-dark" if on_dark else "meter-track"
    label_class = "meter-label-dark" if on_dark else "meter-label-light"
    clamped = max(0, min(score, 100))
    return (
        '<div class="meter">'
        f'<div class="meter-label-row {label_class}"><span>{label}</span><span>{score}%</span></div>'
        f'<div class="{track_class}"><div class="meter-fill meter-fill-{variant}" style="width: {clamped}%;"></div></div>'
        "</div>"
    )


def render_report(report: dict[str, Any], repositories: dict[str, str]) -> None:
    st.markdown('<div class="rule"></div>', unsafe_allow_html=True)
    st.markdown('<div class="eyebrow">Analysis complete</div>', unsafe_allow_html=True)
    has_dual_scores = "avg_composability_score" in report
    score_column, summary_column = st.columns([1, 2], gap="large")
    with score_column:
        if has_dual_scores:
            st.markdown(
                f'<div class="score-panel"><div class="score-label">Composability</div>'
                f'<div class="score-number">{report["avg_composability_score"]}%</div>'
                + meter_bar_html(report["avg_redundancy_score"], "Redundancy", "redundancy", on_dark=True)
                + f'<div class="score-label">{len(repositories)} projects analyzed</div></div>',
                unsafe_allow_html=True,
            )
            text_morph(
                words=[
                    f"{report['avg_composability_score']}% COMPOSABLE",
                    f"{report['avg_redundancy_score']}% REDUNDANT",
                ],
                key="score_text_morph",
            )
        else:
            score = int(report["overlap_score"])
            st.markdown(
                f'<div class="score-panel"><div class="score-label">Reuse potential</div><div class="score-number">{score}%</div><div class="score-label">Average of strongest project relationships · {len(repositories)} projects analyzed</div></div>',
                unsafe_allow_html=True,
            )
    with summary_column, st.container(key="summary_panel", border=False):
        st.markdown("### What can work together")
        st.write(report["summary"])
        st.markdown("**Shared capabilities**")
        st.markdown(" ".join(f'<span class="tag">{item}</span>' for item in report["shared_capabilities"]), unsafe_allow_html=True)
        if has_dual_scores:
            st.markdown("**Complementary pairings**")
            st.markdown(" ".join(f'<span class="tag">{item}</span>' for item in report["composable_pairings"]), unsafe_allow_html=True)
        st.markdown(f"**Suggested next step:** {report['recommendation']}")

    st.markdown("### Project map")
    for project in report["project_summaries"]:
        st.markdown(
            f'<div class="project-card"><strong>{project["repository"]}</strong><div class="project-meta">{project["primary_focus"]}</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("### Strongest overlaps")
    if report["overlaps"]:
        if has_dual_scores:
            st.dataframe(
                [
                    {
                        "rank": item["rank"],
                        "repository_a": item["repository_a"],
                        "repository_b": item["repository_b"],
                        "composability": item["composability_score"],
                        "redundancy": item["redundancy_score"],
                        "tier": item["tier"],
                    }
                    for item in report["overlaps"]
                ],
                hide_index=True,
                width="stretch",
            )
            st.caption("Composable pairs are candidates to stack or integrate. Redundant pairs likely compete — pick one as the base.")
            for item in report["overlaps"]:
                tier_class = TIER_CSS_CLASSES.get(item["tier"], "tier-solid")
                rank_class = RANK_MEDAL_CLASSES.get(item["rank"], "")
                with st.expander(f"{item['repository_a']} × {item['repository_b']}"):
                    st.markdown(
                        f'<span class="rank-badge {rank_class}">#{item["rank"]}</span>'
                        f'<span class="tier-badge {tier_class}">{item["tier"]}</span>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(meter_bar_html(item["composability_score"], "Composability", "composability"), unsafe_allow_html=True)
                    st.markdown(meter_bar_html(item["redundancy_score"], "Redundancy", "redundancy"), unsafe_allow_html=True)
                    st.write(item["evidence"])
                    st.markdown(f"**Next step:** {item['next_step']}")
        else:
            st.dataframe(report["overlaps"], hide_index=True, width="stretch")
            st.caption("Use the highest-scoring relationships as starting points for adapters, shared services, plugins, or a new product layer.")
    else:
        st.info("No meaningful overlap pairs were found in the README excerpts.")

    st.markdown("### Source material")
    for repo, readme in repositories.items():
        with st.expander(f"README excerpt · {repo}"):
            st.code(readme, language="markdown")


st.session_state.setdefault("repo_input", DEFAULT_REPOS)
st.session_state.setdefault("github_results", [])
st.session_state.setdefault("s_tier_streak", 0)
st.session_state.setdefault("achievements_shown", set())

st.markdown('<div class="eyebrow">Cross-team intelligence / 01</div>', unsafe_allow_html=True)
st.title("CrossTalk")
st.markdown("### Cross-team overlap detector")
st.markdown('<p class="lede">Find overlap. Cut waste. Build together. Discover real public projects and compare up to 10 of them side by side.</p>', unsafe_allow_html=True)
if st.session_state["s_tier_streak"] > 0:
    count = st.session_state["s_tier_streak"]
    st.markdown(
        f'<div class="streak-chip">🔥 {count} S-Tier match{"es" if count != 1 else ""} found this session</div>',
        unsafe_allow_html=True,
    )
st.markdown('<div class="rule"></div>', unsafe_allow_html=True)

st.markdown("### Discover public projects")
search_query_column, search_button_column = st.columns([3, 1], gap="medium")
with search_query_column:
    search_query = st.text_input(
        "GitHub search",
        value="authentication middleware",
        help="Search public repositories by tool, capability, or domain. For example: project management, vector database, or API gateway.",
    )
with search_button_column:
    st.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True)
    search_clicked = st.button("Search GitHub", width="stretch")

if search_clicked:
    try:
        with st.spinner("Searching public GitHub repositories..."):
            st.session_state["github_results"] = search_github_repositories(search_query, token=get_github_token())
    except (ValueError, requests.RequestException) as error:
        st.warning(str(error))

if st.session_state["github_results"]:
    results = st.session_state["github_results"]
    st.caption(f"Top {len(results)} public repositories for `{search_query}`. GitHub search is ranked by stars.")
    selected_repositories = card_selector(
        items=[
            {
                "full_name": item["full_name"],
                "stars": item["stars"],
                "language": item["language"],
                "description": item["description"],
                "url": item["url"],
            }
            for item in results
        ],
        key="repo_card_selector",
    )
    st.caption(f"{len(selected_repositories)} selected")
    if st.button("Add selected to analysis", width="content"):
        if not selected_repositories:
            st.warning("Select at least one repository from the search results first.")
        else:
            current = [line.strip() for line in st.session_state["repo_input"].splitlines() if line.strip()]
            merged = list(dict.fromkeys(current + selected_repositories))
            if len(merged) > 10:
                st.warning("Only the first 10 repositories were added. Remove some before adding more.")
            added_count = len(set(merged[:10]) - set(current))
            st.session_state["repo_input"] = "\n".join(merged[:10])
            st.success(f"Added {added_count} {'repository' if added_count == 1 else 'repositories'} to the analysis list.")
            st.rerun()

st.markdown("### Add projects")
raw_repositories = st.text_area(
    "Public GitHub repositories",
    height=150,
    help="Enter one public repository per line in owner/repo format. You can analyze 2 to 10 repositories at once.",
    key="repo_input",
)

if st.button("Analyze overlap", type="primary", width="content"):
    report = None
    with st.status("Reading project documentation...", expanded=True) as status:
        try:
            repository_names = parse_repositories(raw_repositories)
            github_token = get_github_token()
            repositories = {}
            for repo in repository_names:
                st.write(f"Fetching `{repo}`")
                repositories[repo] = fetch_readme(repo, token=github_token)
            analysis_label = "gpt-4o-mini" if get_api_key() else "local composability/redundancy scoring"
            st.write(f"Comparing {len(repositories)} projects with {analysis_label}...")
            report = analyze_overlap(repositories)
            status.update(label="Analysis ready", state="complete", expanded=False)
        except requests.RequestException as error:
            status.update(label="Could not reach GitHub", state="error")
            st.error(f"GitHub request failed: {error}")
        except (ValueError, RuntimeError, json.JSONDecodeError) as error:
            status.update(label="Analysis stopped", state="error")
            st.warning(str(error))
    if report is not None:
        render_report(report, repositories)
        if "first_analysis" not in st.session_state["achievements_shown"]:
            st.session_state["achievements_shown"].add("first_analysis")
            st.toast("Achievement unlocked: first analysis complete!", icon="🎉")
        s_tier_pairs = [item for item in report.get("overlaps", []) if item.get("tier") == "S-TIER MATCH"]
        if s_tier_pairs:
            st.session_state["s_tier_streak"] += len(s_tier_pairs)
            st.balloons()
            if "first_s_tier" not in st.session_state["achievements_shown"]:
                st.session_state["achievements_shown"].add("first_s_tier")
                st.toast("Achievement unlocked: first S-Tier match!", icon="🏆")
            st.toast(f"Streak: {st.session_state['s_tier_streak']} S-Tier match{'es' if st.session_state['s_tier_streak'] != 1 else ''} this session", icon="🔥")

st.markdown('<div class="rule"></div>', unsafe_allow_html=True)
st.caption("CrossTalk MVP · Public README analysis · Uses local composability/redundancy scoring without a key; configure OPENAI_API_KEY for semantic analysis")
