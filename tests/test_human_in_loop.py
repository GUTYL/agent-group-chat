"""单元测试 — 人类参与会话"""

from agc.core.human_in_loop import HumanInTheLoop, HumanMode
from agc.core.message import MessageType


def test_human_mode_off():
    """off模式不暂停"""
    human = HumanInTheLoop(mode=HumanMode.off)
    assert human.should_pause(0) is False
    assert human.should_pause(5) is False


def test_human_mode_always():
    """always模式每轮都暂停"""
    human = HumanInTheLoop(mode=HumanMode.always, name="user")
    assert human.should_pause(0) is True
    assert human.should_pause(5) is True


def test_human_mode_on_demand():
    """on_demand模式不主动暂停"""
    human = HumanInTheLoop(mode=HumanMode.on_demand)
    assert human.should_pause(0) is False


def test_human_input_with_callback():
    """用回调获取人类输入"""
    responses = ["我觉得应该用令牌桶", "skip"]
    idx = [0]

    def callback(round_idx, last_speaker):
        if idx[0] < len(responses):
            resp = responses[idx[0]]
            idx[0] += 1
            return resp if resp != "skip" else None
        return None

    human = HumanInTheLoop(mode=HumanMode.always, name="user", on_input_callback=callback)

    msg = human.get_input(0, "researcher")
    assert msg is not None
    assert msg.sender == "user"
    assert msg.msg_type == MessageType.human_input
    assert msg.content == "我觉得应该用令牌桶"

    # skip 返回 None
    msg2 = human.get_input(1, "architect")
    assert msg2 is None


def test_human_create_factory():
    """工厂方法创建"""
    human = HumanInTheLoop.create("always", name="主持人")
    assert human.mode == HumanMode.always
    assert human.name == "主持人"

    human2 = HumanInTheLoop.create("off")
    assert human2.mode == HumanMode.off

    human3 = HumanInTheLoop.create("unknown")
    assert human3.mode == HumanMode.off