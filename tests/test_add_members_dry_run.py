import sys


def run_cli(argv):
    sys.argv = ["huntstand-add-members", *argv]
    # run the module file directly
    from huntstand_exporter import add_members
    return add_members.main(sys.argv[1:])


def test_add_members_dry_run(tmp_path, monkeypatch):
    # create temporary CSV inputs
    members = tmp_path / "members.csv"
    members.write_text("email\nuser1@example.com\nuser2@example.com\n", encoding="utf-8")
    admins = tmp_path / "admin.csv"
    admins.write_text("email\nadmin@example.com\n", encoding="utf-8")
    view = tmp_path / "view_only.csv"
    view.write_text("email\nviewer@example.com\n", encoding="utf-8")
    hunts = tmp_path / "huntareas.csv"
    hunts.write_text("huntarea_id\n123456\n123457\n", encoding="utf-8")

    # run dry-run limiting roles to member for speed
    monkeypatch.chdir(tmp_path)
    code = run_cli(["--dry-run", "--roles", "member", "--members-file", str(members), "--huntareas-file", str(hunts)])
    assert code == 0

    # Ensure no output file created
    exports_dir = tmp_path / "exports"
    if exports_dir.exists():
        # directory should be absent in dry-run; if present, ensure it is empty
        assert not any(p for p in exports_dir.iterdir() if p.is_file()), "Dry-run should not create result files"
