"""v2 대시보드의 시각 테마."""

THEME_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;600;700;800&display=swap');

    :root {
        --navy: #15233d;
        --blue: #1769e0;
        --blue-soft: #eaf2ff;
        --teal: #07847c;
        --red: #d92d20;
        --orange: #e87817;
        --yellow: #d6a500;
        --line: #dce3ec;
        --muted: #687386;
        --panel: #ffffff;
        --canvas: #f4f7fb;
    }

    html, body, [class*="css"] {
        font-family: 'Noto Sans KR', -apple-system, BlinkMacSystemFont, sans-serif;
    }

    .stApp {
        background: var(--canvas);
        color: var(--navy);
    }

    .block-container {
        max-width: 1500px;
        padding-top: 1.5rem;
        padding-bottom: 3rem;
    }

    header[data-testid="stHeader"] {
        background: transparent;
    }

    .dashboard-header {
        padding: 0.15rem 0 0.45rem;
    }

    .dashboard-kicker {
        color: var(--blue);
        font-size: 0.76rem;
        font-weight: 800;
        letter-spacing: 0.12em;
        margin-bottom: 0.28rem;
    }

    .dashboard-title {
        color: var(--navy);
        font-size: clamp(1.55rem, 3vw, 2.45rem);
        font-weight: 800;
        letter-spacing: -0.04em;
        line-height: 1.15;
        margin: 0;
    }

    .dashboard-subtitle {
        color: var(--muted);
        font-size: 0.9rem;
        margin-top: 0.45rem;
    }

    .status-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 0.75rem;
        margin: 0.85rem 0 1rem;
    }

    .status-card {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 14px;
        min-height: 88px;
        padding: 0.9rem 1rem;
        box-shadow: 0 4px 16px rgba(23, 39, 65, 0.045);
    }

    .status-card__label {
        color: var(--muted);
        font-size: 0.76rem;
        font-weight: 600;
    }

    .status-card__value {
        color: var(--navy);
        font-size: 1.55rem;
        font-weight: 800;
        letter-spacing: -0.03em;
        margin-top: 0.18rem;
    }

    .status-card__note {
        color: var(--muted);
        font-size: 0.72rem;
        margin-top: 0.12rem;
    }

    .status-card--danger { border-top: 3px solid var(--red); }
    .status-card--warning { border-top: 3px solid var(--orange); }
    .status-card--info { border-top: 3px solid var(--blue); }
    .status-card--ok { border-top: 3px solid var(--teal); }

    .alert-summary {
        align-items: flex-start;
        background: #fff4f2;
        border: 1px solid #ffc9c4;
        border-radius: 12px;
        color: #8b2119;
        display: flex;
        gap: 0.75rem;
        margin-bottom: 1rem;
        padding: 0.72rem 0.9rem;
    }

    .alert-summary__badge {
        background: var(--red);
        border-radius: 999px;
        color: white;
        flex: 0 0 auto;
        font-size: 0.72rem;
        font-weight: 800;
        padding: 0.25rem 0.55rem;
    }

    .alert-summary__text {
        font-size: 0.82rem;
        font-weight: 600;
        line-height: 1.5;
    }

    .section-heading {
        align-items: center;
        display: flex;
        justify-content: space-between;
        margin: 0.15rem 0 0.65rem;
    }

    .section-heading h2 {
        color: var(--navy);
        font-size: 1.08rem;
        font-weight: 800;
        margin: 0;
    }

    .section-heading span {
        color: var(--muted);
        font-size: 0.74rem;
    }

    div[data-testid="stVerticalBlockBorderWrapper"] {
        background: var(--panel);
        border-color: var(--line);
        border-radius: 14px;
        box-shadow: 0 4px 16px rgba(23, 39, 65, 0.04);
    }

    .action-card {
        background: #fff;
        border: 1px solid var(--line);
        border-left: 4px solid var(--blue);
        border-radius: 10px;
        margin-bottom: 0.55rem;
        padding: 0.72rem 0.78rem;
    }

    .action-card--high { border-left-color: var(--red); background: #fffafa; }
    .action-card--medium { border-left-color: var(--orange); }
    .action-card--low { border-left-color: var(--yellow); }

    .action-card__top {
        align-items: center;
        display: flex;
        gap: 0.45rem;
        justify-content: space-between;
    }

    .action-card__name {
        color: var(--navy);
        font-size: 0.86rem;
        font-weight: 700;
    }

    .action-card__grade {
        border-radius: 999px;
        color: white;
        flex: 0 0 auto;
        font-size: 0.67rem;
        font-weight: 800;
        padding: 0.18rem 0.45rem;
    }

    .grade-high { background: var(--red); }
    .grade-medium { background: var(--orange); }
    .grade-low { background: #a67d00; }

    .action-card__meta {
        color: var(--muted);
        font-size: 0.72rem;
        line-height: 1.4;
        margin-top: 0.32rem;
    }

    .weather-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 0.6rem;
        margin-top: 0.8rem;
    }

    .facility-metadata {
        background: #f6f9fd;
        border: 1px solid #e4eaf2;
        border-radius: 11px;
        margin: 0.8rem 0;
        overflow: hidden;
    }

    .facility-metadata__row {
        padding: 0.7rem 0.8rem;
    }

    .facility-metadata__row + .facility-metadata__row {
        border-top: 1px solid #e4eaf2;
    }

    .facility-metadata__label {
        color: var(--muted);
        font-size: 0.72rem;
        font-weight: 600;
        margin-bottom: 0.2rem;
    }

    .facility-metadata__value {
        color: var(--navy);
        font-size: 0.92rem;
        font-weight: 600;
        line-height: 1.55;
        overflow-wrap: anywhere;
        word-break: keep-all;
        white-space: normal;
    }

    .weather-card {
        background: #f6f9fd;
        border: 1px solid #e4eaf2;
        border-radius: 11px;
        padding: 0.72rem;
    }

    .weather-card__label { color: var(--muted); font-size: 0.72rem; }
    .weather-card__value {
        color: var(--navy);
        font-size: 1.3rem;
        font-weight: 800;
        margin-top: 0.2rem;
    }

    div[data-testid="stButton"] > button,
    div[data-testid="stDownloadButton"] > button {
        border-radius: 10px;
        font-weight: 700;
    }

    div[data-testid="stSegmentedControl"] {
        margin-bottom: 0.75rem;
    }

    @media (max-width: 767px) {
        .block-container {
            padding-left: 1rem;
            padding-right: 1rem;
            padding-top: 0.8rem;
        }

        .dashboard-kicker { font-size: 0.68rem; }
        .dashboard-title { font-size: 1.72rem; }
        .dashboard-subtitle { font-size: 0.8rem; }

        .status-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.55rem;
        }

        .status-card {
            min-height: 76px;
            padding: 0.7rem 0.75rem;
        }

        .status-card__value { font-size: 1.28rem; }
        .alert-summary { padding: 0.65rem 0.7rem; }
        .alert-summary__text { font-size: 0.75rem; }
        .weather-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }

        .st-key-header-actions div[data-testid="stHorizontalBlock"] {
            flex-wrap: nowrap !important;
            gap: 0.5rem !important;
        }

        .st-key-header-actions div[data-testid="stColumn"] {
            flex: 1 1 calc(50% - 0.25rem) !important;
            min-width: 0 !important;
            width: calc(50% - 0.25rem) !important;
        }
    }
</style>
"""
