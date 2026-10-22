"""Cleaning rules of the silver layer."""

from credit.silver import clean_applications, clean_installments, clean_previous_applications

APP_COLUMNS = [
    "SK_ID_CURR", "TARGET", "NAME_CONTRACT_TYPE", "CODE_GENDER", "FLAG_OWN_CAR", "FLAG_OWN_REALTY", "CNT_CHILDREN",
    "AMT_INCOME_TOTAL", "AMT_CREDIT", "AMT_ANNUITY", "AMT_GOODS_PRICE", "NAME_INCOME_TYPE", "NAME_EDUCATION_TYPE",
    "NAME_FAMILY_STATUS", "NAME_HOUSING_TYPE", "OCCUPATION_TYPE", "ORGANIZATION_TYPE", "REGION_RATING_CLIENT_W_CITY",
    "DAYS_BIRTH", "DAYS_EMPLOYED", "EXT_SOURCE_1", "EXT_SOURCE_2", "EXT_SOURCE_3",
]  # fmt: skip


def app(id_, gender="F", days_employed="-3652", occupation="Laborers"):
    return (
        id_, "0", "Cash loans", gender, "Y", "N", "0", "200000", "400000", "20000", "380000", "Working",
        "Higher education", "Married", "House / apartment", occupation, "Self-employed", "2", "-14610",
        days_employed, "", "0.5", "0.6",
    )  # fmt: skip


def test_applications_cleaning(spark):
    bronze = spark.createDataFrame(
        [app("1"), app("1"), app("2", gender="XNA", days_employed="365243", occupation=None)], APP_COLUMNS
    )
    rows = {r.application_id: r for r in clean_applications(bronze).collect()}
    assert len(rows) == 2  # duplicate application removed
    assert rows[1].years_employed == 10.0 and not rows[1].employment_not_reported
    # 365243 is a code for "not reported", never 1,000 years of work
    assert rows[2].years_employed is None and rows[2].employment_not_reported
    assert rows[2].gender is None  # unknown gender code
    assert rows[2].occupation == "Not informed"
    assert rows[1].age_years == 40.0
    assert rows[1].payment_to_income == 0.1
    assert rows[1].external_score_1 is None  # empty text -> missing value


def test_installments_parts_are_combined(spark):
    cols = ["SK_ID_PREV", "SK_ID_CURR", "NUM_INSTALMENT_VERSION", "NUM_INSTALMENT_NUMBER", "DAYS_INSTALMENT",
            "DAYS_ENTRY_PAYMENT", "AMT_INSTALMENT", "AMT_PAYMENT"]  # fmt: skip
    bronze = spark.createDataFrame(
        [
            ("10", "1", "1", "1", "-100", "-105", "1000", "600"),  # paid in two parts:
            ("10", "1", "1", "1", "-100", "-90", "1000", "400"),  # last part 10 days late
            ("10", "1", "1", "2", "-70", "-75", "1000", "1000"),  # on time
            ("10", "1", "1", "3", "-40", None, "1000", None),  # never paid
            ("10", "1", "1", "4", "-10", "-12", "1000", "500"),  # underpaid
        ],
        cols,
    )
    rows = {r.installment_number: r for r in clean_installments(bronze).collect()}
    assert len(rows) == 4
    assert rows[1].amount_paid == 1000 and rows[1].days_late == 10 and rows[1].paid_late
    assert rows[2].days_late == 0 and not rows[2].paid_late
    assert rows[3].never_paid and rows[3].amount_paid == 0
    assert rows[4].underpaid and not rows[2].underpaid


def test_previous_applications_keep_last_version_only(spark):
    cols = ["SK_ID_PREV", "SK_ID_CURR", "NAME_CONTRACT_TYPE", "AMT_APPLICATION", "AMT_CREDIT", "NAME_CONTRACT_STATUS",
            "DAYS_DECISION", "CODE_REJECT_REASON", "FLAG_LAST_APPL_PER_CONTRACT", "NFLAG_LAST_APPL_IN_DAY"]  # fmt: skip
    bronze = spark.createDataFrame(
        [
            ("1", "1", "Cash loans", "100", "100", "Approved", "-365", "XAP", "Y", "1"),
            ("2", "1", "Cash loans", "100", "0", "Refused", "-30", "HC", "N", "1"),  # superseded version
            ("3", "1", "Cash loans", "100", "0", "Canceled", "-30", "XAP", "Y", "0"),  # not the last of the day
        ],
        cols,
    )
    result = clean_previous_applications(bronze).collect()
    assert [r.previous_application_id for r in result] == [1]
    assert result[0].years_since_decision == 1.0
