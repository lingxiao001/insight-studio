import copy
import json
import time

import httpx
import pytest

from app.billing import BudgetLedger
from app.config import Settings
from app.ingest import demo_dataset
from app.analysis import analyze
from app.llm import enrich, review_model_assertions
from app.store import Store

KEY = "sk-or-v1-test-credential-never-return"
MODEL = "test/fixed-model"


@pytest.mark.parametrize("text", [
    "就业能力自评越高，真实就业率越高。",
    "实习成绩较高的学生更容易获得录用。",
    "就业率提高10%，薪资也随之上升。",
    "不能推断因果，但这组学生的就业率达到90%。",
])
def test_employment_self_report_does_not_become_observed_employment(text):
    flags = review_model_assertions([text], focus="employment_ability_scale")
    assert "将就业能力自评误读为真实就业结果" in flags


@pytest.mark.parametrize("text", [
    "就业能力自评不是实际就业率，不能据此断言就业率提高。",
    "不能推断实习成绩提高会带来薪资提高。",
    "需要收集就业率提高或下降的真实记录来验证。",
    "尚无证据说明就业率达到90%。",
    "可先了解学生如何理解问卷题目。",
])
def test_self_report_review_allows_measurement_warnings_and_data_requests(text):
    assert review_model_assertions([text], focus="employment_ability_scale") == []


def test_employment_guard_is_scoped_to_self_report_target():
    assert review_model_assertions(["所选组就业率为90%。"], focus="observed_employment_rate") == []


@pytest.fixture
def analysis():
    df, source = demo_dataset()
    return analyze(df, source, "寻找销售机会", "销售额", lambda *args: None)


@pytest.fixture
def ledger(tmp_path):
    settings = Settings(data_dir=tmp_path, llm_key=KEY, llm_model=MODEL,
                        llm_input_price="0.132", llm_output_price="0.396", llm_provider_only="test/fp8")
    settings.validate()
    store = Store(tmp_path)
    store.seed_admin("admin", "test-hash-not-used-for-login")
    user = store.add_user("member", "test-hash-not-used-for-login")
    return BudgetLedger(store, settings).for_user(user["id"])


def mock_provider(monkeypatch, content, captured, *, cost="0.00012", status=200,
                  fail=False, finish="stop", usage=True, response_override=None):
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url, **kwargs):
            if url.endswith("/key"):
                body = {"data": {"is_management_key": False}}
            else:
                body = {"data": {"endpoints": [{"tag": "test/fp8", "provider_name": "Test",
                    "pricing": {"prompt": "0.000000132", "completion": "0.000000396"},
                    "supported_parameters": ["max_tokens", "response_format", "reasoning_effort"]}]}}
            return httpx.Response(200, json=body, request=httpx.Request("GET", url))
        def post(self, endpoint, headers, json):
            captured.append(json)
            if fail:
                raise httpx.ReadTimeout("private details must never be returned")
            body = response_override if response_override is not None else {"id": "gen-test", "model": MODEL, "provider": "Test",
                "choices": [{"finish_reason": finish, "message": {"content": content}}]}
            if usage and response_override is None:
                body["usage"] = {"cost": cost, "prompt_tokens": 123, "completion_tokens": 456}
            return httpx.Response(status, json=body, request=httpx.Request("POST", endpoint))
    monkeypatch.setattr("app.billing.httpx.Client", Client)


@pytest.mark.parametrize("malformed", ["[]", "null", "42", "not json", '{"summary":"should not appear","insights":42}',
                                       '{"summary":"should not appear","insights":[{"title":"valid","body":"partial"}],"recommendations":[42]}'])
def test_bad_model_output_is_billed_and_preserves_fallback(analysis, ledger, monkeypatch, malformed):
    result, aggregates = analysis
    before = copy.deepcopy(result)
    mock_provider(monkeypatch, malformed, [])
    enrich(result, aggregates, "goal", None, ledger.settings, ledger)
    assert result["summary"] == before["summary"] and result["insights"] == before["insights"]
    assert result["agent"]["mode"] == "statistical"
    assert "已记录实际费用" in result["agent"]["notes"][-1]
    assert ledger.usage()["spent_usd"] == .00012 and ledger.usage()["reserved_usd"] == 0


def test_success_receives_only_aggregates_and_has_hard_provider_caps(analysis, ledger, monkeypatch):
    result, aggregates = analysis
    captured = []
    mock_provider(monkeypatch, json.dumps({"summary": "概览", "narrative": "按目标开展分组验证。",
        "insights": [{"title": "验证", "body": "进一步验证分组差异。"}], "recommendations": ["比较分组"]}), captured, cost="0.0001201")
    enrich(result, aggregates, "寻找销售机会", "销售额", ledger.settings, ledger)
    assert result["agent"]["mode"] == "llm" and result["agent"]["model"] == MODEL
    sent = captured[0]["messages"][1]["content"]
    assert "寻找销售机会" in sent and "dataset_aggregates" in sent
    assert "preview" not in sent and "ORD-100001" not in sent and "线上商城" not in sent
    assert KEY not in json.dumps(result)
    assert captured[0]["provider"] == {"only": ["test/fp8"], "allow_fallbacks": False,
        "require_parameters": True, "zdr": True, "max_price": {"prompt": .132, "completion": .396}}
    assert captured[0]["max_tokens"] == 3200 and captured[0]["reasoning"] == {"effort": "none"}
    assert not captured[0].get("tools") and captured[0]["plugins"] == []
    usage = ledger.usage()
    assert usage["spent_usd"] == .000121
    assert usage["prompt_tokens"] == 123 and usage["completion_tokens"] == 456
    assert usage["request_count"] == 1 and usage["uncertain_usd"] == 0
    assert "$1" in " ".join(result["agent"]["notes"]) and "$5" not in " ".join(result["agent"]["notes"])


def test_billed_model_employment_misreading_is_withheld_without_replacing_brief(analysis, ledger, monkeypatch):
    result, aggregates = analysis
    result["brief"]["focus"]["column"] = "employment_ability_scale"
    before = copy.deepcopy(result)
    captured = []
    mock_provider(monkeypatch, json.dumps({"summary": "实习成绩高的学生就业率提高10%。",
                                          "narrative": "这组学生更容易获得录用。"}), captured)
    enrich(result, aggregates, "解释就业能力自评", "employment_ability_scale", ledger.settings, ledger)
    assert len(captured) == 1 and ledger.usage()["spent_usd"] == .00012
    assert result["agent"]["mode"] == "statistical"
    assert result["brief"] == before["brief"] and result["summary"] == before["summary"]
    assert result["insights"] == before["insights"]
    assert "将就业能力自评误读为真实就业结果" in " ".join(result["agent"]["notes"])


def test_admin_model_usage_note_has_no_cumulative_limit(analysis, ledger, monkeypatch):
    result, aggregates = analysis
    admin = ledger.for_user(ledger.store.admin_user()["id"])
    captured = []
    mock_provider(monkeypatch, json.dumps({"summary":"概览","narrative":"继续核对分组样本量。"}), captured)
    enrich(result, aggregates, "goal", None, admin.settings, admin)
    assert result["agent"]["mode"] == "llm"
    assert "不设应用内累计额度上限" in " ".join(result["agent"]["notes"])
    assert "$5" not in " ".join(result["agent"]["notes"])
    assert admin.usage()["spent_usd"] == .00012 and ledger.usage()["spent_usd"] == 0


@pytest.mark.parametrize("failure", ["timeout", "missing_cost", "server_error", "invalid_cost"])
def test_unknown_charges_hold_full_reservation_without_retry(analysis, ledger, monkeypatch, failure):
    result, aggregates = analysis
    captured = []
    options = {"fail": failure == "timeout", "usage": failure != "missing_cost"}
    if failure == "server_error":
        options.update(status=503, response_override={"error": {"code": 503, "message": "provider unavailable"}})
    if failure == "invalid_cost": options["cost"] = "NaN"
    mock_provider(monkeypatch, "{}", captured, **options)
    enrich(result, aggregates, "goal", None, ledger.settings, ledger)
    usage = ledger.usage()
    assert len(captured) == 1 and usage["request_count"] == 1
    assert usage["uncertain_usd"] > .01 and usage["spent_usd"] == 0
    assert usage["reserved_usd"] == 0 and result["agent"]["mode"] == "statistical"
    assert "private details" not in json.dumps(result)


def test_explicit_preinference_rejection_has_no_charge(analysis, ledger, monkeypatch):
    result, aggregates = analysis
    captured = []
    mock_provider(monkeypatch, "", captured, status=402,
                  response_override={"error": {"code": 402, "message": "insufficient credits"}})
    enrich(result, aggregates, "goal", None, ledger.settings, ledger)
    usage = ledger.usage()
    assert len(captured) == 1 and usage["spent_usd"] == usage["uncertain_usd"] == usage["reserved_usd"] == 0
    assert usage["remaining_usd"] == 1 and usage["request_count"] == 1
    assert "HTTP 402" in usage["last_error"] and "insufficient credits" in usage["last_error"]


def test_provider_diagnostic_redacts_secrets_input_and_metadata(analysis, ledger, monkeypatch):
    result, aggregates = analysis
    captured = []
    goal = "private business goal content"
    message = ("No endpoints found: " + KEY + " sk-or-v1-another-private-token " + goal
               + ' {"messages":[{"content":"must-never-appear"}]}\nprivate second line')
    mock_provider(monkeypatch, "", captured, status=404, response_override={"error": {
        "code": 404, "message": message, "metadata": {"raw": "metadata-must-never-appear", "api_key": KEY}}})
    enrich(result, aggregates, goal, None, ledger.settings, ledger)
    visible = json.dumps({"notes": result["agent"]["notes"], "error": ledger.usage()["last_error"]}, ensure_ascii=False)
    assert "HTTP 404" in visible and "No endpoints found" in visible
    for secret in [KEY, "sk-or-v1-another-private-token", goal, "must-never-appear", "private second line", "metadata-must-never-appear"]:
        assert secret not in visible
    assert len(captured) == 1 and ledger.usage()["spent_usd"] == 0


def test_provider_diagnostic_is_bounded_and_never_returns_error_object(analysis, ledger, monkeypatch):
    result, aggregates = analysis
    mock_provider(monkeypatch, "", [], status=400, response_override={"error": {
        "code": 400, "message": "Invalid parameter " + "x" * 1000,
        "metadata": {"raw_response": "private-raw-data"}}})
    enrich(result, aggregates, "goal", None, ledger.settings, ledger)
    error = ledger.usage()["last_error"]
    assert "HTTP 400" in error and len(error) < 330 and "private-raw-data" not in error


def test_zdr_account_violation_is_detected_after_first_line_without_echoing_input(analysis, ledger, monkeypatch):
    result, aggregates = analysis
    message = ("0 endpoints out of 1 requested are available matching your guardrail restrictions and data policy.\n"
               "ZDR violation (account settings): 1 endpoint excluded; configurable at https://openrouter.ai/settings/privacy\n"
               + KEY + " unknown-private-input")
    mock_provider(monkeypatch, "", [], status=404, response_override={"error": {"code": 404, "message": message}})
    enrich(result, aggregates, "goal", None, ledger.settings, ledger)
    visible = json.dumps({"notes": result["agent"]["notes"], "error": ledger.usage()["last_error"]}, ensure_ascii=False)
    assert "HTTP 404" in visible
    assert "账户要求零数据保留（ZDR），指定端点不符合；请保留隐私设置并配置支持 ZDR 的旗舰端点。" in visible
    assert "https://" not in visible and KEY not in visible and "unknown-private-input" not in visible
    assert ledger.usage()["spent_usd"] == 0 and ledger.usage()["uncertain_usd"] == 0


def test_truncated_response_is_still_billed(analysis, ledger, monkeypatch):
    result, aggregates = analysis
    before = copy.deepcopy(result)
    captured = []
    mock_provider(monkeypatch, '{"summary":"truncated', captured, finish="length")
    enrich(result, aggregates, "goal", None, ledger.settings, ledger)
    assert ledger.usage()["spent_usd"] == .00012 and result["agent"]["mode"] == "statistical"
    assert len(captured) == 1 and result["summary"] == before["summary"]
    assert "没有自动重试" in result["agent"]["notes"][-1]


def test_complete_sentences_over_prompt_targets_keep_their_qualifications(analysis,ledger,monkeypatch):
    result,aggregates = analysis
    qualification = "以上仅为当前样本的描述性比较，不能推断因果。"
    body = {"summary":"既有聚合证据可供后续核查。"*7+qualification,
        "narrative":"聚合证据用于后续核查。"*45+qualification,
        "insights":[{"title":"核查","body":"检查已有分组支持数。"*13+qualification} for _ in range(5)],
        "recommendations":["后续核验业务口径。"*7+qualification for _ in range(5)]}
    mock_provider(monkeypatch,json.dumps(body,ensure_ascii=False),[])
    enrich(result,aggregates,"goal",None,ledger.settings,ledger)
    assert result["agent"]["mode"] == "llm"
    assert len(body["narrative"]) > 450 and result["agent"]["narrative"] == body["narrative"]
    model_insights = [item for item in result["insights"] if item["title"].startswith("Agent · ")]
    assert len(model_insights) == 3 and all(item["body"] == body["insights"][0]["body"] for item in model_insights)
    assert result["recommendations"][:3] == body["recommendations"][:3]
    assert result["summary"].endswith(body["summary"])
    assert all(item["body"].endswith(qualification) for item in model_insights)
    assert all(item.endswith(qualification) for item in result["recommendations"][:3])


def test_large_deep_evidence_is_compacted_before_paid_call_without_losing_scope(analysis, ledger, monkeypatch):
    result,aggregates = analysis
    numeric_profile = next(column for column in aggregates["columns"] if column["kind"] == "numeric")
    aggregates["columns"] = [dict(numeric_profile,name=f"field_{i}_"+"n"*180) for i in range(80)]
    assert len(json.dumps(aggregates,ensure_ascii=False)) > 32_000
    captured = []
    mock_provider(monkeypatch,json.dumps({"summary":"概览","narrative":"根据聚合证据开展验证。","insights":[],"recommendations":[]}),captured)
    enrich(result,aggregates,"关注销售额","销售额",ledger.settings,ledger)
    assert len(captured) == 1 and result["agent"]["mode"] == "llm"
    sent = captured[0]["messages"][1]["content"]
    assert len(sent) <= 32_000
    payload = json.loads(sent)
    evidence = payload["dataset_aggregates"]["eda_evidence"]
    assert evidence["groups"] and evidence["time"] and evidence["distributions"]
    assert evidence["groups"][0]["selection_note"]
    assert "12" in evidence["time"][0]["selection_note"]
    assert payload["source_limits"]
    assert len(aggregates["columns"]) == 80  # Compaction does not mutate stored evidence.
    assert "线上商城" not in sent and "数码配件" not in sent


def test_real_unverified_shape_and_factor_response_is_billed_but_not_adopted(analysis, ledger, monkeypatch):
    result,aggregates = analysis
    before = copy.deepcopy(result)
    # Replay the observed successful provider response's unsupported claims;
    # no network or extra model call is made by this regression.
    narrative = ("销售额整体分布接近对称，均值421.47，中位数421，标准差140.21，偏度0.01，峰度-0.75。"
        "这说明销售额集中在300至525之间，分布较为均匀，没有明显长尾。"
        "地区间差异幅度不足6个单位，远小于整体标准差，说明地区不是销售额的主要区分因素。"
        "件数在三个地区完全相同，进一步支持地区间同质性。"
        "这提示销售额的波动可能更多来自单价或其他未提供因素，而不是件数。")
    captured = []
    mock_provider(monkeypatch,json.dumps({"summary":"应被整批收起的模型摘要","narrative":narrative,
        "insights":[{"title":"模型洞察","body":"分布较为均匀。"}],"recommendations":["按模型结论行动"]}),captured)
    enrich(result,aggregates,"关注销售额","销售额",ledger.settings,ledger)
    assert len(captured) == 1 and ledger.usage()["spent_usd"] == .00012
    assert result["summary"] == before["summary"] and result["insights"] == before["insights"]
    assert result["recommendations"] == before["recommendations"]
    assert result["agent"]["mode"] == "statistical" and not result["agent"].get("narrative")
    notes = " ".join(result["agent"]["notes"])
    assert "按实际费用结算" in notes and "没有自动重试" in notes
    assert "分布形状" in notes and "影响因素" in notes and "不代表已全面验证" in notes


@pytest.mark.parametrize("text",[
    "偏度接近零，但不能据此证明分布对称或正态。",
    "没有证据证明销售额分布是对称的。",
    "不能仅凭组均值相近就认为地区不是主要区分因素。",
    "建议进一步验证分布是否对称，不能把当前统计当成检验。",
    "分布接近对称的假设有待验证。",
    "分布的对称性仍需进一步验证。",
    "分布的对称性还需进一步检验。",
    "分布的对称性尚需验证。",
    "销售额波动可能更多来自单价而不是件数，但这只是有待验证的假设。",
    "Pearson 和 Spearman 均接近零，当前样本未见明显线性或单调关联，不能排除其他关系。",
])
def test_conservative_negation_and_validation_advice_are_not_withheld(text):
    assert review_model_assertions([text]) == []


def test_direct_shape_assertion_is_still_withheld_after_suffix_fix():
    assert review_model_assertions(["销售额整体分布接近对称，分布较为均匀，没有明显长尾。"])


def test_unrelated_caution_before_contrast_does_not_exempt_shape_assertion():
    assert review_model_assertions(["不能推断因果，但销售额分布接近对称。"])
    assert review_model_assertions(["不能依据均值判断分布对称。"] ) == []


@pytest.mark.parametrize("text", [
    "行政区价格差异显著。",
    "整租房源价格显著高于其他房型。",
    "未做显著性检验，但价格差异显著。",
    "不能推断因果，整租房源价格显著高于其他房型。",
    "行政区之间的价格差异不显著。",
    "各组没有显著差异。",
    "经度越靠西价格越低。",
    "向东价格更高。",
    "北部房源租金较低。",
])
def test_unexamined_significance_and_spatial_claims_are_withheld(text):
    assert review_model_assertions([text])


@pytest.mark.parametrize("text", [
    "尚未做显著性检验，不能判断差异是否显著。",
    "未做显著性检验，不能判断差异显著。",
    "差异不代表统计显著。",
    "当前只能比较组均值与中位数，不宣称差异显著。",
    "不能从经度相关认定越西价格越低。",
    "经度与价格的 Pearson r 为负，只能描述所选记录的线性关联。",
])
def test_significance_cautions_and_uninterpreted_coordinates_are_allowed(text):
    assert review_model_assertions([text]) == []


def test_real_airbnb_significance_and_direction_replay_is_billed_not_adopted(analysis, ledger, monkeypatch):
    result, aggregates = analysis
    before = copy.deepcopy(result)
    captured = []
    mock_provider(monkeypatch, json.dumps({
        "summary": "行政区价格差异显著。",
        "narrative": "整租房源价格显著高于其他房型，经度越靠西价格越低。",
        "insights": [{"title": "空间比较", "body": "不能推断因果，整租房源价格显著高于其他房型。"}],
        "recommendations": ["根据这些结论调整定价。"],
    }), captured, cost="0.005536")
    enrich(result, aggregates, "比较当前挂牌价", "price", ledger.settings, ledger)
    assert len(captured) == 1 and ledger.usage()["spent_usd"] == .005536
    assert result["summary"] == before["summary"] and result["insights"] == before["insights"]
    assert result["recommendations"] == before["recommendations"]
    assert result["agent"]["mode"] == "statistical" and not result["agent"].get("narrative")
    notes = " ".join(result["agent"]["notes"])
    assert "显著性" in notes and "方位" in notes
    assert "按实际费用结算" in notes and "没有自动重试" in notes


@pytest.mark.parametrize("channel",["summary","insight","recommendation"])
def test_unverified_assertions_are_checked_in_every_model_text_channel(analysis, ledger, monkeypatch,channel):
    result,aggregates = analysis
    before = copy.deepcopy(result)
    body = {"summary":"数值概览","narrative":"请结合分位数和样本量核对已有描述性证据。","insights":[],"recommendations":[]}
    if channel == "summary": body["summary"] = "销售额分布接近对称。"
    if channel == "insight": body["insights"] = [{"title":"地区判断","body":"这说明地区不是销售额的主要区分因素。"}]
    if channel == "recommendation": body["recommendations"] = ["据此判定该数据分布较为均匀，没有明显长尾。"]
    mock_provider(monkeypatch,json.dumps(body),[])
    enrich(result,aggregates,"goal",None,ledger.settings,ledger)
    assert result["summary"] == before["summary"] and result["insights"] == before["insights"]
    assert result["recommendations"] == before["recommendations"]
    assert ledger.usage()["spent_usd"] == .00012 and result["agent"]["mode"] == "statistical"


def test_reasonable_conservative_model_response_is_adopted(analysis, ledger, monkeypatch):
    result,aggregates = analysis
    body = {"summary":"统计范围内的分位数与组内样本量可用于后续验证。",
        "narrative":"偏度接近零，但不能据此证明分布对称。不能仅凭组均值相近就认定地区不是主要区分因素。建议进一步验证分布是否对称，并核对分组支持数。",
        "insights":[{"title":"继续验证","body":"当前只能比较已提供的均值、中位数与四分位数，不宣称差异显著。"}],
        "recommendations":["保留业务假设，使用独立数据检验。"]}
    mock_provider(monkeypatch,json.dumps(body),[])
    enrich(result,aggregates,"goal",None,ledger.settings,ledger)
    assert result["agent"]["mode"] == "llm" and result["agent"]["narrative"] == body["narrative"]
    assert ledger.usage()["spent_usd"] == .00012
