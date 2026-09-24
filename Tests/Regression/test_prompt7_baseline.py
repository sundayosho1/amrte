from amrte.app import build_engine
from amrte.core.constants import AMRTE_VERSION


def test_prompt1_through_6_baseline_and_version():
    engine=build_engine()
    assert engine.state_machine.state.name=="READY"
    assert tuple(map(int,AMRTE_VERSION.split(".")))>=(0,7,0)
    assert engine.configuration.values["execution.available"] is False
