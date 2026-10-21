"""Reproducible Isolation Forest and aligned, imputed inputs for downstream SHAP."""
import hashlib
import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline


DEFAULT_FEATURES = ["payment_value","payment_installments","payment_sequential"]


def train(frame, output, *, table="order_payments", features=None, id_column="order_id", amount_column="payment_value", contamination=0.01, decisions=()):
    if features is None:
        blocked={item.get("column") for item in decisions if item.get("table")==table and
                 (item.get("action")!="keep" or item.get("semantic_type") in {"PERSONAL_ID","INTERNAL_KEY","BUSINESS_KEY","POSTAL_CODE"})}
        features=[column for column in DEFAULT_FEATURES if column in frame and column not in blocked]
    features = list(features)
    if not features or len(features)>20 or len(set(features))!=len(features) or not set(features).issubset(frame.columns):
        raise ValueError("ANOMALY_COLUMNS: select between one and twenty distinct numeric columns")
    if id_column in {"source_row","anomaly_score","is_anomaly","is_model_anomaly","invalid_features","invalid_amount"}:
        raise ValueError("ANOMALY_COLUMNS: selected identifier conflicts with an output column")
    if id_column and id_column not in frame:
        raise ValueError("ANOMALY_COLUMNS: selected identifier is absent")
    for column in features:
        protected = any(item.get("table")==table and item.get("column")==column and
                        (item.get("action")!="keep" or item.get("semantic_type") in {"PERSONAL_ID","INTERNAL_KEY","BUSINESS_KEY","POSTAL_CODE"}) for item in decisions)
        if protected or column.lower().endswith(("_id","_key")):
            raise ValueError("ANOMALY_PROTECTED: identifiers and protected columns cannot be model features")
    if len(frame)<2:
        raise ValueError("ANOMALY_ROWS: at least two rows are required")
    if not 0<float(contamination)<=0.5:
        raise ValueError("ANOMALY_THRESHOLD: contamination must be greater than zero and at most 0.5")
    values=frame[features].apply(pd.to_numeric,errors="coerce").replace([np.inf,-np.inf],np.nan)
    if not values.notna().any().any():
        raise ValueError("ANOMALY_NUMBERS: selected columns contain no usable numbers")
    model=Pipeline([("imputer",SimpleImputer(strategy="median",keep_empty_features=True)),
                    ("isolation_forest",IsolationForest(random_state=42,n_estimators=100,contamination=float(contamination),n_jobs=1))])
    model.fit(values)
    transformed=model.named_steps["imputer"].transform(values)
    scores=pd.DataFrame({"source_row":np.arange(len(frame),dtype=np.int64)})
    for column in dict.fromkeys([id_column,"payment_sequential"]):
        if column and column in frame and column not in scores:
            scores[column]=frame[column].to_numpy()
    scores["anomaly_score"]=-model.score_samples(values)
    scores["is_model_anomaly"]=model.predict(values)==-1
    scores["invalid_features"]=values.isna().any(axis=1).to_numpy()
    scores["invalid_amount"]=False
    if amount_column:
        if amount_column not in frame:
            raise ValueError("ANOMALY_COLUMNS: selected amount column is absent")
        amount=pd.to_numeric(frame[amount_column],errors="coerce").replace([np.inf,-np.inf],np.nan)
        scores["invalid_amount"]=(amount.isna() | amount.lt(0)).to_numpy()
    scores["is_anomaly"]=scores.is_model_anomaly | scores.invalid_amount | scores.invalid_features
    feature_columns=[]
    for i,column in enumerate(features):
        feature_column=f"feature__{column}"
        if feature_column in scores:
            raise ValueError("ANOMALY_COLUMNS: feature output name collision")
        feature_columns.append(feature_column)
        scores[f"input__{column}"]=values[column].to_numpy()
        scores[feature_column]=transformed[:,i]
    model_path=output/"anomaly_model.joblib"
    joblib.dump(model,model_path)
    scores_path=output/"anomaly_scores.parquet"
    scores.to_parquet(scores_path,index=False)
    background=sorted(np.random.default_rng(42).choice(len(frame),size=min(100,len(frame)),replace=False).tolist())
    report={"schema_version":"bo2-local-1","table":table,"features":features,"rows":len(frame),
            "flagged":int(scores.is_anomaly.sum()),"seed":42,"policy":"flag_only_never_delete",
            "model_type":"IsolationForest","n_estimators":100,"contamination":float(contamination),
            "model_flagged":int(scores.is_model_anomaly.sum()),"invalid_amount_rows":int(scores.invalid_amount.sum()),
            "invalid_feature_rows":int(scores.invalid_features.sum()),"id_column":id_column,"amount_column":amount_column,
            "score_definition":"-pipeline.score_samples(X); larger means more unusual; this is not a probability",
            "decision_offset":float(model.named_steps["isolation_forest"].offset_),
            "missing_per_feature":{col:int(values[col].isna().sum()) for col in features},
            "imputation":{"strategy":"median","empty_feature_fill":0,"values":dict(zip(features,model.named_steps["imputer"].statistics_.tolist()))},
            "versions":{"sklearn":sklearn.__version__,"joblib":joblib.__version__,"numpy":np.__version__},
            "model_sha256":hashlib.sha256(model_path.read_bytes()).hexdigest(),
            "scores_sha256":hashlib.sha256(scores_path.read_bytes()).hexdigest(),
            "shap":{"computed":False,"estimator_step":"isolation_forest","preprocessing_step":"imputer",
                    "feature_order":features,"transformed_feature_columns":feature_columns,
                    "scores_file":"anomaly_scores.parquet","model_file":"anomaly_model.joblib",
                    "source_row_column":"source_row","background_source_rows":background,
                    "instructions":"Use the transformed feature columns in feature_order with the fitted estimator. Do not impute these columns again. SHAP contributions have not been computed; do not interpret them as anomaly_score contributions without checking the explainer output."}}
    return scores,report
