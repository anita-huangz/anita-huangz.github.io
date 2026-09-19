"""A null result, established properly: no learnable signal in this dataset."""

from .data import (
    Dataset,
    SchemaError,
    TemplateReport,
    label_index_correlation,
    load,
    template_report,
)
from .signal import (
    DetectableEffect,
    FeatureTest,
    LearningCurve,
    PermutationTest,
    auc_on_folds,
    build_pipeline,
    cross_validated_auc,
    feature_tests,
    gradient_boosting,
    learning_curve,
    minimum_detectable_auc,
    permutation_test,
    prepare_folds,
)

__all__ = [
    "Dataset",
    "DetectableEffect",
    "FeatureTest",
    "LearningCurve",
    "PermutationTest",
    "SchemaError",
    "TemplateReport",
    "auc_on_folds",
    "build_pipeline",
    "cross_validated_auc",
    "feature_tests",
    "gradient_boosting",
    "label_index_correlation",
    "learning_curve",
    "load",
    "minimum_detectable_auc",
    "permutation_test",
    "prepare_folds",
    "template_report",
]
