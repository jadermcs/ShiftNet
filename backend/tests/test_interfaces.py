import json

import anyio
import pytest

from shiftnet_backend import cli


def test_cli_import_and_dry_run(database_url, tmp_path, capsys):
    f = tmp_path / "senses.jsonl"
    f.write_text(json.dumps({"lemma": "doomscroll", "pos": "verb", "gloss": "to keep reading bad news online",
                             "date_label": "2018", "date_earliest": 2018, "source": "Corpus", "source_type": "corpus"}) + "\n")
    assert cli.main(["import", str(f), "--dry-run"]) == 0
    assert "Checked 1 senses: doomscroll.v.01" in capsys.readouterr().out
    assert cli.main(["import", str(f)]) == 0
    assert cli.main(["import", str(f)]) == 0  # no id: a second sense, not an update
    assert "doomscroll.v.02" in capsys.readouterr().out


def test_cli_rejects_invalid_rows(database_url, tmp_path, capsys):
    f = tmp_path / "bad.json"
    f.write_text(json.dumps([{"lemma": "x", "pos": "noun", "gloss": "", "date_label": "1", "date_earliest": 1,
                              "source": "s", "source_type": "corpus"}]))
    assert cli.main(["import", str(f)]) == 1
    assert "gloss" in capsys.readouterr().err


@pytest.mark.parametrize("write", [False, True])
def test_mcp_tools(database_url, monkeypatch, write):
    import importlib

    monkeypatch.setenv("SHIFTNET_MCP_WRITE", "1" if write else "0")
    from shiftnet_backend import mcp_server

    mcp_server = importlib.reload(mcp_server)
    names = {t.name for t in anyio.run(mcp_server.server.list_tools)}
    read = {"search_lexicon", "get_word", "get_sense", "list_candidates", "get_candidate", "get_relation_suggestions"}
    writes = {"save_senses", "add_attestation", "match_candidate", "promote_candidate", "reject_candidate", "discover_senses",
              "suggest_relations"}
    assert names == (read | writes if write else read)

    assert mcp_server.get_sense("cloud.n.06")["gloss"].startswith("remote servers")
    assert [s["id"] for s in mcp_server.get_word("cloud")][:2] == ["cloud.n.01", "cloud.n.02"]
    if write:
        from shiftnet_backend.models import SenseIn

        ids = mcp_server.save_senses([SenseIn(lemma="cloud", pos="verb", gloss="to store online", date_label="2010s",
                                              date_earliest=2010, shift="metaphor", source="s", source_type="corpus",
                                              parents=[{"parent_id": "cloud.n.06"}])])
        assert ids == ["cloud.v.03"]
