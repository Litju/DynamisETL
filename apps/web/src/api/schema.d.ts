export interface paths {
    "/api/artifacts/{artifact_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Artifact */
        get: operations["artifact_api_artifacts__artifact_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/artifacts/{artifact_id}/window": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Artifact Window */
        get: operations["artifact_window_api_artifacts__artifact_id__window_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/catalog/datasets": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Datasets */
        get: operations["list_datasets_api_catalog_datasets_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/catalog/datasets/{dataset_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Dataset Detail */
        get: operations["dataset_detail_api_catalog_datasets__dataset_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/catalog/datasets/{dataset_id}/sessions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Sessions */
        get: operations["list_sessions_api_catalog_datasets__dataset_id__sessions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/catalog/datasets/{dataset_id}/sessions/{session_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Session Detail */
        get: operations["session_detail_api_catalog_datasets__dataset_id__sessions__session_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/derived-metrics/{derived_metric_id}/provenance": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Provenance */
        get: operations["provenance_api_derived_metrics__derived_metric_id__provenance_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Health */
        get: operations["health_api_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/metrics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Metrics */
        get: operations["metrics_api_metrics_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/metrics/methodology/{metric_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Methodology */
        get: operations["methodology_api_metrics_methodology__metric_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/quality": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Quality */
        get: operations["quality_api_quality_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/rights": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Rights */
        get: operations["rights_api_rights_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/runs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Runs */
        get: operations["runs_api_runs_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/serving/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Serving Status */
        get: operations["serving_status_api_serving_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AlgorithmView */
        AlgorithmView: {
            /** Algorithm Id */
            algorithm_id: string;
            /** Citation */
            citation: string | null;
            /** Code Git Sha */
            code_git_sha: string | null;
            /** Description */
            description: string | null;
            /** Kind */
            kind: string;
            /** Name */
            name: string;
            /** Parameters */
            parameters: {
                [key: string]: unknown;
            };
            /** Parameters Hash */
            parameters_hash: string | null;
            /** Version */
            version: string;
        };
        /**
         * ArtifactDetail
         * @description One artifact plus the canonical time bounds of its samples.
         *
         *     The bounds require reading the Parquet footer/column statistics, so they are
         *     served only for a single requested artifact and never inside a list
         *     response. A laboratory uses them to choose a deterministic first window
         *     instead of asking the reader to guess a time range.
         */
        ArtifactDetail: {
            /** Artifact Id */
            artifact_id: string;
            /**
             * Artifact Kind
             * @enum {string}
             */
            artifact_kind: "sample" | "processing";
            /** Byte Size */
            byte_size: number | null;
            /** Canonical Time Max Ns */
            canonical_time_max_ns?: number | null;
            /** Canonical Time Min Ns */
            canonical_time_min_ns?: number | null;
            /** Checksum Sha256 */
            checksum_sha256: string;
            /** Compression */
            compression: string | null;
            /** Coordinate Frame Id */
            coordinate_frame_id: string | null;
            /** Dataset Id */
            dataset_id: string;
            /** Entity Column */
            entity_column?: string | null;
            /** Entity Count */
            entity_count?: number | null;
            /** Format */
            format: string;
            /** Layer */
            layer: string;
            /** Measurement Class */
            measurement_class: string | null;
            /** Modality */
            modality: string | null;
            /** Relative Path */
            relative_path: string;
            /** Row Count */
            row_count: number;
            /** Si Units */
            si_units: string[];
            /** Stream Id */
            stream_id: string | null;
            /** Synchronization Spec Id */
            synchronization_spec_id: string | null;
        };
        /** ArtifactRefView */
        ArtifactRefView: {
            /** Artifact Id */
            artifact_id: string;
            /**
             * Artifact Kind
             * @enum {string}
             */
            artifact_kind: "sample" | "processing";
            /** Byte Size */
            byte_size: number | null;
            /** Checksum Sha256 */
            checksum_sha256: string;
            /** Compression */
            compression: string | null;
            /** Coordinate Frame Id */
            coordinate_frame_id: string | null;
            /** Dataset Id */
            dataset_id: string;
            /** Format */
            format: string;
            /** Layer */
            layer: string;
            /** Measurement Class */
            measurement_class: string | null;
            /** Modality */
            modality: string | null;
            /** Relative Path */
            relative_path: string;
            /** Row Count */
            row_count: number;
            /** Si Units */
            si_units: string[];
            /** Stream Id */
            stream_id: string | null;
            /** Synchronization Spec Id */
            synchronization_spec_id: string | null;
        };
        /** DatasetDetail */
        DatasetDetail: {
            /** Adapter Id */
            adapter_id: string;
            /** Dataset Id */
            dataset_id: string;
            /** Doi */
            doi: string | null;
            /** Domain */
            domain: string;
            /** Initial Scope */
            initial_scope: string;
            license: components["schemas"]["LicenseView"];
            /** Metric Count */
            metric_count: number;
            /** Modalities */
            modalities: string[];
            /** Name */
            name: string;
            /** Provider */
            provider: string;
            /** Quality Issue Count */
            quality_issue_count: number;
            /** Session Count */
            session_count: number;
            /** Stream Count */
            stream_count: number;
            /** Subject Count */
            subject_count: number;
            /** Trial Count */
            trial_count: number;
            /** Upstream Urls */
            upstream_urls: string[];
            /** V1 Role */
            v1_role: string;
            /** Version Count */
            version_count: number;
            /** Versions */
            versions: components["schemas"]["DatasetVersionView"][];
        };
        /** DatasetSummary */
        DatasetSummary: {
            /** Dataset Id */
            dataset_id: string;
            /** Doi */
            doi: string | null;
            /** Domain */
            domain: string;
            license: components["schemas"]["LicenseView"];
            /** Metric Count */
            metric_count: number;
            /** Modalities */
            modalities: string[];
            /** Name */
            name: string;
            /** Provider */
            provider: string;
            /** Quality Issue Count */
            quality_issue_count: number;
            /** Session Count */
            session_count: number;
            /** Stream Count */
            stream_count: number;
            /** Subject Count */
            subject_count: number;
            /** Trial Count */
            trial_count: number;
            /** Upstream Urls */
            upstream_urls: string[];
            /** Version Count */
            version_count: number;
        };
        /** DatasetVersionView */
        DatasetVersionView: {
            /** Citation */
            citation: string | null;
            /** Release Date */
            release_date: string | null;
            /** Retrieval Status */
            retrieval_status: string;
            /** Retrieved At */
            retrieved_at: string | null;
            /** Upstream Url */
            upstream_url: string;
            /** Version */
            version: string;
        };
        /** DenseWindow */
        DenseWindow: {
            meta: components["schemas"]["DenseWindowMeta"];
            /** Rows */
            rows: {
                [key: string]: unknown;
            }[];
        };
        /** DenseWindowMeta */
        DenseWindowMeta: {
            artifact: components["schemas"]["ArtifactRefView"];
            /** Canonical Time Max Ns */
            canonical_time_max_ns: number | null;
            /** Canonical Time Min Ns */
            canonical_time_min_ns: number | null;
            /** Columns */
            columns: string[];
            /** Coordinate Frame Id */
            coordinate_frame_id: string | null;
            /** Display Note */
            display_note: string;
            /** From Ns */
            from_ns: number;
            /** Measurement Class */
            measurement_class: string | null;
            reduction: components["schemas"]["ReductionInfo"] | null;
            /** Returned Rows */
            returned_rows: number;
            /** Source Rows */
            source_rows: number;
            /** To Ns */
            to_ns: number;
            /** Units */
            units: {
                [key: string]: string;
            };
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** HealthStatus */
        HealthStatus: {
            /**
             * Status
             * @constant
             */
            status: "ok";
            /** Version */
            version: string;
        };
        /**
         * LicenseView
         * @description Declared license/rights policy as stored by the rights authority.
         */
        LicenseView: {
            /** Attribution Required */
            attribution_required: boolean;
            /** Identifier */
            identifier: string | null;
            /** Local Only */
            local_only: boolean;
            /** Noncommercial Only */
            noncommercial_only: boolean;
            /** Notice */
            notice: string;
            /** Policy Id */
            policy_id: string;
            /** Redistribution */
            redistribution: string;
            /** Restrictions */
            restrictions: unknown[];
            /** Share Alike */
            share_alike: boolean;
            /** Status */
            status: string;
        };
        /** MetricDefinitionView */
        MetricDefinitionView: {
            /** Algorithm Id */
            algorithm_id: string | null;
            /** Description */
            description: string | null;
            /** Measurement Class */
            measurement_class: string;
            /** Metric Id */
            metric_id: string;
            /** Name */
            name: string;
            /** Si Unit */
            si_unit: string;
            /** Value Kind */
            value_kind: string;
        };
        /** MetricMethodology */
        MetricMethodology: {
            algorithm: components["schemas"]["AlgorithmView"] | null;
            /** Measurement Class Never Means */
            measurement_class_never_means: string[];
            /** Measurement Class Semantics */
            measurement_class_semantics: string;
            metric: components["schemas"]["MetricDefinitionView"];
            /** Provenance Fields */
            provenance_fields: string[];
        };
        /** MetricPage */
        MetricPage: {
            /** Limit */
            limit: number;
            /** Offset */
            offset: number;
            /** Rows */
            rows: components["schemas"]["MetricValue"][];
            /**
             * Source
             * @enum {string}
             */
            source: "gold" | "control_plane";
            /** Total */
            total: number;
        };
        /**
         * MetricValue
         * @description One derived metric value with its full provenance envelope.
         */
        MetricValue: {
            /** Algorithm Id */
            algorithm_id: string | null;
            /** Algorithm Version */
            algorithm_version: string | null;
            /** Code Git Sha */
            code_git_sha: string | null;
            /** Computed At */
            computed_at: string | null;
            /** Dataset Id */
            dataset_id: string;
            /** Derived Metric Id */
            derived_metric_id: string;
            /** Entity Id */
            entity_id: string | null;
            /** Measurement Class */
            measurement_class: string;
            /** Metric Description */
            metric_description: string | null;
            /** Metric Id */
            metric_id: string;
            /** Metric Name */
            metric_name: string | null;
            /** Parameters Hash */
            parameters_hash: string | null;
            /** Provenance */
            provenance: {
                [key: string]: unknown;
            };
            /** Run Id */
            run_id: string;
            /** Session Id */
            session_id: string | null;
            /** Si Unit */
            si_unit: string;
            /** Stream Id */
            stream_id: string | null;
            /** Subject Id */
            subject_id: string | null;
            /** Trial Id */
            trial_id: string | null;
            /** Value Json */
            value_json: {
                [key: string]: unknown;
            } | null;
            /** Value Kind */
            value_kind: string;
            /** Value Num */
            value_num: number | null;
        };
        /** ProvenanceEdge */
        ProvenanceEdge: {
            /** Id */
            id: string;
            /** Label */
            label: string;
            /** Source */
            source: string;
            /** Target */
            target: string;
        };
        /** ProvenanceGraph */
        ProvenanceGraph: {
            /** Derived Metric Id */
            derived_metric_id: string;
            /** Edges */
            edges: components["schemas"]["ProvenanceEdge"][];
            /** Lineage Note */
            lineage_note: string;
            /** Nodes */
            nodes: components["schemas"]["ProvenanceNode"][];
            /** Provenance */
            provenance: {
                [key: string]: unknown;
            };
        };
        /** ProvenanceNode */
        ProvenanceNode: {
            /** Details */
            details: {
                [key: string]: unknown;
            };
            /** Id */
            id: string;
            /** Kind */
            kind: string;
            /** Label */
            label: string;
            /** Measurement Class */
            measurement_class?: string | null;
            /** Status */
            status?: string | null;
        };
        /** QualityIssuePage */
        QualityIssuePage: {
            /** Limit */
            limit: number;
            /** Offset */
            offset: number;
            /** Rows */
            rows: components["schemas"]["QualityIssueView"][];
            /** Total */
            total: number;
        };
        /** QualityIssueView */
        QualityIssueView: {
            /** Dataset Id */
            dataset_id: string;
            /** Detected At */
            detected_at: string | null;
            /** Evidence */
            evidence: {
                [key: string]: unknown;
            };
            /** Issue Id */
            issue_id: string;
            /** Rule */
            rule: string;
            /** Run Id */
            run_id: string | null;
            /** Sample Index */
            sample_index: number | null;
            /** Session Id */
            session_id: string | null;
            /** Severity */
            severity: string;
            /** State */
            state: string;
            /** Stream Id */
            stream_id: string | null;
            /** Subject Id */
            subject_id: string | null;
            /** Trial Id */
            trial_id: string | null;
        };
        /**
         * ReductionInfo
         * @description Explicit display-reduction record; never a scientific transformation.
         */
        ReductionInfo: {
            /** Method */
            method: string;
            /** Note */
            note: string;
            /** Parameters */
            parameters: {
                [key: string]: unknown;
            };
            /** Returned Points */
            returned_points: number;
            /** Source Points */
            source_points: number;
        };
        /** RightsPage */
        RightsPage: {
            /** Policies */
            policies: components["schemas"]["RightsPolicyView"][];
        };
        /** RightsPolicyView */
        RightsPolicyView: {
            /** Dataset Ids */
            dataset_ids: string[];
            license: components["schemas"]["LicenseView"];
        };
        /** RunPage */
        RunPage: {
            /** Limit */
            limit: number;
            /** Offset */
            offset: number;
            /** Rows */
            rows: components["schemas"]["RunView"][];
            /** Total */
            total: number;
        };
        /** RunView */
        RunView: {
            /** Algorithm Id */
            algorithm_id: string;
            /** Algorithm Name */
            algorithm_name: string | null;
            /** Algorithm Version */
            algorithm_version: string | null;
            /** Artifact Count */
            artifact_count: number;
            /** Code Git Sha */
            code_git_sha: string | null;
            /** Completed At */
            completed_at: string | null;
            /** Dataset Id */
            dataset_id: string;
            /** Input Checksums */
            input_checksums: string[];
            /** Kind */
            kind: string | null;
            /** Metric Count */
            metric_count: number;
            /** Notes */
            notes: string | null;
            /** Parameters Hash */
            parameters_hash: string | null;
            /** Run Id */
            run_id: string;
            /** Started At */
            started_at: string | null;
            /** Status */
            status: string;
        };
        /** ServingStatus */
        ServingStatus: {
            /**
             * Database
             * @enum {string}
             */
            database: "ok" | "unavailable";
            /** Dataset Count */
            dataset_count: number;
            /** Db Schema */
            db_schema: string;
            /** Gold Published */
            gold_published: boolean;
            /** Gold Schema */
            gold_schema: string;
            /** Metric Count */
            metric_count: number;
            /** Quality Issue Count */
            quality_issue_count: number;
            /** Run Count */
            run_count: number;
        };
        /** SessionDetail */
        SessionDetail: {
            /** Dataset Id */
            dataset_id: string;
            /** Participants */
            participants: components["schemas"]["SessionParticipantView"][];
            session: components["schemas"]["SessionSummary"];
            /** Streams */
            streams: components["schemas"]["StreamView"][];
            /** Trials */
            trials: components["schemas"]["TrialView"][];
        };
        /** SessionParticipantView */
        SessionParticipantView: {
            /** Group Label */
            group_label: string | null;
            /** Role */
            role: string;
            /** Subject Id */
            subject_id: string;
        };
        /** SessionSummary */
        SessionSummary: {
            /** Ended At */
            ended_at: string | null;
            /** Kind */
            kind: string;
            /** Label */
            label: string | null;
            /** Participant Count */
            participant_count: number;
            /** Session Id */
            session_id: string;
            /** Started At */
            started_at: string | null;
            /** Stream Count */
            stream_count: number;
            /** Trial Count */
            trial_count: number;
        };
        /** StreamView */
        StreamView: {
            /** Clock Id */
            clock_id: string;
            /** Coordinate Frame Id */
            coordinate_frame_id: string | null;
            /** Device Id */
            device_id: string | null;
            /** Measurement Class */
            measurement_class: string;
            /** Modality */
            modality: string;
            /** Nominal Sampling Rate Hz */
            nominal_sampling_rate_hz: number | null;
            /** Sample Artifact Ids */
            sample_artifact_ids: string[];
            /** Sample Row Count */
            sample_row_count: number;
            /** Si Units */
            si_units: string[];
            /** Skeleton Id */
            skeleton_id: string | null;
            /** Source Unit */
            source_unit: string | null;
            /** Stream Id */
            stream_id: string;
            /** Subject Id */
            subject_id: string | null;
            /** Synchronization Spec Id */
            synchronization_spec_id: string;
            /** Trial Id */
            trial_id: string | null;
        };
        /** TrialView */
        TrialView: {
            /** Ended At */
            ended_at: string | null;
            /** Label */
            label: string | null;
            /** Parent Trial Id */
            parent_trial_id: string | null;
            /** Started At */
            started_at: string | null;
            /** Subject Id */
            subject_id: string | null;
            /** Trial Id */
            trial_id: string;
        };
        /** ValidationError */
        ValidationError: {
            /** Context */
            ctx?: Record<string, never>;
            /** Input */
            input?: unknown;
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    artifact_api_artifacts__artifact_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    artifact_window_api_artifacts__artifact_id__window_get: {
        parameters: {
            query?: {
                from_ns?: number | null;
                to_ns?: number | null;
                columns?: string | null;
                max_points?: number | null;
                entity_id?: string | null;
                format?: string;
            };
            header?: never;
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DenseWindow"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_datasets_api_catalog_datasets_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DatasetSummary"][];
                };
            };
        };
    };
    dataset_detail_api_catalog_datasets__dataset_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                dataset_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DatasetDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_sessions_api_catalog_datasets__dataset_id__sessions_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                dataset_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionSummary"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    session_detail_api_catalog_datasets__dataset_id__sessions__session_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                dataset_id: string;
                session_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    provenance_api_derived_metrics__derived_metric_id__provenance_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                derived_metric_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProvenanceGraph"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    health_api_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthStatus"];
                };
            };
        };
    };
    metrics_api_metrics_get: {
        parameters: {
            query?: {
                dataset_id?: string | null;
                session_id?: string | null;
                subject_id?: string | null;
                trial_id?: string | null;
                stream_id?: string | null;
                metric_id?: string | null;
                entity_id?: string | null;
                limit?: number;
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MetricPage"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    methodology_api_metrics_methodology__metric_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                metric_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MetricMethodology"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    quality_api_quality_get: {
        parameters: {
            query?: {
                dataset_id?: string | null;
                session_id?: string | null;
                severity?: string | null;
                limit?: number;
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QualityIssuePage"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    rights_api_rights_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RightsPage"];
                };
            };
        };
    };
    runs_api_runs_get: {
        parameters: {
            query?: {
                dataset_id?: string | null;
                limit?: number;
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunPage"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    serving_status_api_serving_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ServingStatus"];
                };
            };
        };
    };
}
