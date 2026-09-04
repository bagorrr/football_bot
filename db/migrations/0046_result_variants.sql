ALTER TABLE football_runtime.recommendation_results
    DROP CONSTRAINT IF EXISTS recommendation_results_result_class_check;

ALTER TABLE football_runtime.recommendation_results
    ADD CONSTRAINT recommendation_results_result_class_check CHECK (
        result_class IN (
            'confirmed_match', 'partial_result', 'possible_match',
            'variant_with_difference'
        )
    );
