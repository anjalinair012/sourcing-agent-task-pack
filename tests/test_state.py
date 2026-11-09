from sourcing_agent.state import State


def test_state_survives_reload(tmp_path):
    s = State(tmp_path / "state.json")
    s.vacancy("VAC-001")["seen"]["PROF-1"] = {"name": "A"}
    s.save()
    again = State(tmp_path / "state.json")
    assert again.vacancy("VAC-001")["seen"] == {"PROF-1": {"name": "A"}}
