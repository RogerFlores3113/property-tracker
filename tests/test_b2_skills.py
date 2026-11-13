"""The skill files, the plugin files, and the Connect and Skills pages working end to end with them."""
import io
import json
import re
import zipfile
from pathlib import Path

import pytest

from prophelper import integrations, routes_skills, skills_install

ROOT = Path(__file__).resolve().parents[1]
CLAUDE = ROOT / "skills" / "claude" / "property-helper" / "SKILL.md"
CODEX = ROOT / "skills" / "codex" / "property-helper" / "SKILL.md"
TOOLS = {"get_overview", "list_places", "get_place", "add_place", "add_places", "update_place", "move_place", "add_note",
         "add_tour", "update_tour", "add_contact", "log_contact", "set_commute", "set_location", "compare_places",
         "todays_list", "create_search", "update_search"}


def front_matter(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, "missing front matter"
    return dict(line.split(": ", 1) for line in m.group(1).splitlines())


@pytest.mark.parametrize("path", [CLAUDE, CODEX])
def test_skill_files_are_well_formed_and_carry_the_rules(path):
    body = path.read_text(encoding="utf-8")
    fm = front_matter(body)
    assert fm["name"] == "property-helper" and len(fm["description"]) > 80
    assert "—" not in body and "–" not in body  # no em or en dashes
    flat = " ".join(body.split()).lower()
    for must in ("never an instruction", "you never delete", "<untrusted>", "ask the user before you contact anyone",
                 "terms", "stricter scraping guards", "5 places per call and 20 per hour", "listing_text", "ai_notes",
                 "todays_list", "compare_places", "you never send it", "uiuc", "$1,600", "own routing lookups",
                 "forward or to passed", "never write the user's own notes"):
        assert must in flat, must
    # every tool the server offers is named, and nothing named as a tool is missing from the server
    for tool in TOOLS:
        assert f"`{tool}`" in body, tool
    named = set(re.findall(r"`([a-z]+(?:_[a-z]+)+)`", body)) - {"in_unit", "in_building", "listing_text", "ai_notes", "min_score", "max_cost",
                                                                  "add_criteria_list"}
    unknown = {n for n in named if n not in TOOLS and n not in ("lease_months", "year_built", "available_from", "other_monthly_fees",
                                                                 "utilities_included", "move_in_fees", "pet_fee", "application_fee", "photo_urls",
                                                                     "pet_kind", "pet_weight", "pet_count", "fenced_yard", "months_up_front",
                                                                     "tenant_pays")}
    assert not unknown, unknown


def test_the_two_skills_give_the_same_advice():
    claude, codex = CLAUDE.read_text(encoding="utf-8"), CODEX.read_text(encoding="utf-8")
    assert claude.split("\n# Property Helper\n", 1)[1].split("## When to use it", 1)[1] == \
        codex.split("\n# Property Helper\n", 1)[1].split("## When to use it", 1)[1]
    assert "restart Codex" in codex and "Codex" not in claude.split("---", 2)[1]


def test_plugin_and_marketplace_files():
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert plugin["name"] == "property-helper" and plugin["skills"] == "./skills/claude/"
    assert plugin["homepage"] == "https://github.com/rogerflores3113/property-helper"
    assert market["name"] == "property-helper" and market["plugins"][0]["name"] == "property-helper"
    assert market["plugins"][0]["source"] == "./"
    assert (ROOT / plugin["skills"]).is_dir()
    assert skills_install.PLUGIN_MANIFEST["homepage"] == plugin["homepage"]
    assert "—" not in json.dumps(plugin) + json.dumps(market)


def test_readme_names_the_real_files_and_commands():
    readme = (ROOT / "skills" / "README.md").read_text(encoding="utf-8")
    assert "skills/claude/property-helper/SKILL.md" in readme and "skills/codex/property-helper/SKILL.md" in readme
    assert "Job App Tracker" not in readme and "jobapps" not in readme and "—" not in readme
    assert "/plugin install property-helper@property-helper" in readme


def test_packaging_includes_the_skill_and_plugin_folders():
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert '"skills" = "prophelper/skills"' in pyproject and '".claude-plugin" = "prophelper/.claude-plugin"' in pyproject
    spec = (ROOT / "packaging" / "property-helper.spec").read_text()
    assert '"skills"' in spec and '".claude-plugin"' in spec


# ----------------------------------------------------------------------------------------------------- the pages
def test_skills_source_dir_finds_the_real_files():
    d = routes_skills.skills_source_dir()
    assert (d / "claude" / "property-helper" / "SKILL.md").is_file() and (d / "codex" / "property-helper" / "SKILL.md").is_file()
    for key in ("claude", "codex"):
        p = routes_skills.plan(key)
        assert p["state"] in ("new", "installed", "update") and p["size"] > 1000 and "Property Helper" in p["text"]


def test_skills_page_shows_the_real_skill_and_installs_and_uninstalls_it(client, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "home" / ".codex"))
    html = client.get("/skills").text
    assert "property-helper" in html and "SKILL.md" in html and "unavailable" not in html.lower()
    assert "Property Helper keeps the user" in html or "name: property-helper" in html  # the file text is shown before writing
    r = client.post("/skills/install", data={"target": "claude"}, follow_redirects=False)
    assert r.status_code == 303
    dest = tmp_path / "home" / ".claude" / "skills" / "property-helper" / "SKILL.md"
    assert dest.read_bytes() == CLAUDE.read_bytes()
    assert routes_skills.plan("claude")["state"] == "installed"
    r = client.post("/skills/install", data={"target": "codex"}, follow_redirects=False)
    assert (tmp_path / "home" / ".codex" / "skills" / "property-helper" / "SKILL.md").read_bytes() == CODEX.read_bytes()
    client.post("/skills/uninstall", data={"target": "claude"}, follow_redirects=False)
    assert not dest.exists()
    assert (tmp_path / "home" / ".codex" / "skills" / "property-helper" / "SKILL.md").exists()  # only what was asked


def test_a_skill_file_the_user_made_is_left_alone(client, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    dest = tmp_path / "home" / ".claude" / "skills" / "property-helper" / "SKILL.md"
    dest.parent.mkdir(parents=True)
    dest.write_text("my own skill")
    assert routes_skills.plan("claude")["state"] == "foreign"
    client.post("/skills/install", data={"target": "claude"}, follow_redirects=False)
    assert dest.read_text() == "my own skill"


def test_plugin_download_is_the_real_plugin(client):
    r = client.get("/skills/property-helper.plugin")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = set(z.namelist())
        assert names == {".claude-plugin/plugin.json", "skills/property-helper/SKILL.md"}
        assert z.read("skills/property-helper/SKILL.md") == CLAUDE.read_bytes()
        manifest = json.loads(z.read(".claude-plugin/plugin.json"))
        assert manifest["name"] == "property-helper" and manifest["homepage"].endswith("/rogerflores3113/property-helper")
    assert skills_install.build_plugin() == skills_install.build_plugin()  # the same bytes every time


def test_save_plugin_to_downloads_and_the_connect_page_offers_it(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROPHELPER_DOWNLOADS_DIR", str(tmp_path / "dl"))
    (tmp_path / "dl").mkdir()
    r = client.post("/skills/plugin/save")
    assert r.status_code == 200 and (tmp_path / "dl" / "property-helper.plugin").is_file()
    page = client.get("/connect").text
    assert "property-helper" in page and "plugin" in page.lower()


def test_the_real_server_starts_through_the_connect_check():
    """What the Connect page's test button does: start the entry the way Claude Desktop would, speak MCP to it, count the tools."""
    spec = integrations.mcp_launch_spec()
    result = integrations.check_launch(spec.as_json_entry(), timeout=60)
    assert result["ok"], result
    assert result["tools"] == len(TOOLS)
    assert result["server_name"] == "property-helper"
    assert not result["stray_stdout"]  # nothing but protocol on stdout
    assert "answered with 18 tools" in integrations.result_line(result)


def test_mcp_subcommand_runs_the_server_not_the_not_built_yet_message():
    from prophelper import cli
    import inspect

    src = inspect.getsource(cli.main)
    assert "run_stdio" in src
    from prophelper.mcp_server import run_stdio
    assert callable(run_stdio)
