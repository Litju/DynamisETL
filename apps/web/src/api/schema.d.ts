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
    "/api/artifacts/{artifact_id}/observations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Artifact Observations */
        get: operations["artifact_observations_api_artifacts__artifact_id__observations_get"];
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
    "/api/metrics/definitions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Metric Definitions */
        get: operations["metric_definitions_api_metrics_definitions_get"];
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
    "/api/ready": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Ready */
        get: operations["ready_api_ready_get"];
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
    "/api/tactical/artifacts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Tactical Artifacts */
        get: operations["tactical_artifacts_api_tactical_artifacts_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tactical/capabilities/{dataset_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Tactical Capabilities */
        get: operations["tactical_capabilities_api_tactical_capabilities__dataset_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tactical/events/{artifact_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Tactical Events */
        get: operations["tactical_events_api_tactical_events__artifact_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tactical/methodology": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Tactical Methodology */
        get: operations["tactical_methodology_api_tactical_methodology_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tactical/quality/{dataset_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Tactical Quality */
        get: operations["tactical_quality_api_tactical_quality__dataset_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tactical/series/{artifact_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Tactical Series */
        get: operations["tactical_series_api_tactical_series__artifact_id__get"];
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
            /** Algorithm Id */
            algorithm_id?: string | null;
            /** Algorithm Version */
            algorithm_version?: string | null;
            /** Artifact Id */
            artifact_id: string;
            /**
             * Artifact Kind
             * @enum {string}
             */
            artifact_kind: "sample" | "processing";
            /** Artifact Metadata */
            artifact_metadata?: {
                [key: string]: unknown;
            };
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
            /** Entity Ids */
            entity_ids?: string[] | null;
            /** Entity Observations */
            entity_observations?: components["schemas"]["EntityObservationView"][] | null;
            /** Format */
            format: string;
            /** Layer */
            layer: string;
            /** Measurement Class */
            measurement_class: string | null;
            /** Modality */
            modality: string | null;
            /** Parameters Hash */
            parameters_hash?: string | null;
            /** Relative Path */
            relative_path: string;
            /** Row Count */
            row_count: number;
            /** Run Id */
            run_id?: string | null;
            /** Si Units */
            si_units: string[];
            /** Stream Id */
            stream_id: string | null;
            /** Synchronization Spec Id */
            synchronization_spec_id: string | null;
        };
        /** ArtifactRefView */
        ArtifactRefView: {
            /** Algorithm Id */
            algorithm_id?: string | null;
            /** Algorithm Version */
            algorithm_version?: string | null;
            /** Artifact Id */
            artifact_id: string;
            /**
             * Artifact Kind
             * @enum {string}
             */
            artifact_kind: "sample" | "processing";
            /** Artifact Metadata */
            artifact_metadata?: {
                [key: string]: unknown;
            };
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
            /** Parameters Hash */
            parameters_hash?: string | null;
            /** Relative Path */
            relative_path: string;
            /** Row Count */
            row_count: number;
            /** Run Id */
            run_id?: string | null;
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
        /**
         * EntityObservationView
         * @description Stable observed-frame bounds for one entity in a dense artifact.
         */
        EntityObservationView: {
            /** Entity Id */
            entity_id: string;
            /** First Observed Ns */
            first_observed_ns: number;
            /** Last Observed Ns */
            last_observed_ns: number;
            /** Observation Count */
            observation_count: number;
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
        /**
         * MetricCatalogEntry
         * @description One registered metric plus where it is actually served.
         *
         *     `dataset_ids` and `value_count` come from the derived rows, so the catalog
         *     can distinguish a metric the registry defines from one the pipeline has
         *     genuinely computed; discovery should not offer the former as if it were
         *     analysable.
         */
        MetricCatalogEntry: {
            /** Algorithm Id */
            algorithm_id: string | null;
            /** Dataset Ids */
            dataset_ids: string[];
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
            /** Value Count */
            value_count: number;
            /** Value Kind */
            value_kind: string;
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
            /** Cohort */
            cohort?: string | null;
            /** Group Label */
            group_label: string | null;
            /** Notes */
            notes?: string | null;
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
        /** SkeletonDisplayConnectionView */
        SkeletonDisplayConnectionView: {
            /** End Joint Name */
            end_joint_name: string;
            /** Start Joint Name */
            start_joint_name: string;
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
            /** Skeleton Display Connections */
            skeleton_display_connections?: components["schemas"]["SkeletonDisplayConnectionView"][];
            /** Skeleton Id */
            skeleton_id: string | null;
            /** Skeleton Joint Names */
            skeleton_joint_names?: string[];
            /** Skeleton Topology */
            skeleton_topology?: string | null;
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
        /** TacticalCapabilityLevels */
        TacticalCapabilityLevels: {
            /** Level A Geometry */
            level_a_geometry: string;
            /** Level B Territory */
            level_b_territory: string;
            /** Level C Influence */
            level_c_influence: string;
            /** Level D Event Linked */
            level_d_event_linked: string;
            /** Level E Shape Phase */
            level_e_shape_phase: string;
        };
        /** TacticalCapabilityView */
        TacticalCapabilityView: {
            /** Accepted Slice */
            accepted_slice: {
                [key: string]: unknown;
            };
            capabilities: components["schemas"]["TacticalCapabilityLevels"];
            /** Dataset Id */
            dataset_id: string;
            /** Quality Evidence */
            quality_evidence: {
                [key: string]: unknown;
            };
            /** Semantics */
            semantics: {
                [key: string]: unknown;
            };
            /** Unavailable Reasons */
            unavailable_reasons: string[];
        };
        /** TacticalEventPage */
        TacticalEventPage: {
            meta: components["schemas"]["TacticalSeriesMeta"];
            /** Rows */
            rows: components["schemas"]["TacticalEventView"][];
        };
        /** TacticalEventView */
        TacticalEventView: {
            /** Ball X M */
            ball_x_m: number | null;
            /** Ball Y M */
            ball_y_m: number | null;
            /** Event Ball Distance M */
            event_ball_distance_m: number | null;
            /** Event Id */
            event_id: string;
            /** Event Subtype */
            event_subtype: string | null;
            /** Event Type */
            event_type: string;
            /** Event X M */
            event_x_m: number | null;
            /** Event Y M */
            event_y_m: number | null;
            /** Provider Context Json */
            provider_context_json: string | null;
            /** Provider Player Id */
            provider_player_id: string | null;
            /** Provider Team Id */
            provider_team_id: string | null;
            /** Quality Json */
            quality_json: string;
            /** T Rel Ns */
            t_rel_ns: number;
            /** Tracking Player Count */
            tracking_player_count: number;
            /** Tracking T Rel Ns */
            tracking_t_rel_ns: number | null;
            /** Tracking Team Count */
            tracking_team_count: number;
        };
        /** TacticalMethodologyPage */
        TacticalMethodologyPage: {
            /** Authority */
            authority: string;
            /** Metrics */
            metrics: components["schemas"]["TacticalMetricMethodologyView"][];
        };
        /** TacticalMetricMethodologyView */
        TacticalMetricMethodologyView: {
            /** Algorithm Id */
            algorithm_id?: string | null;
            /** Algorithm Version */
            algorithm_version?: string | null;
            /** Definition */
            definition: string;
            /** Kind */
            kind: string;
            /**
             * Level
             * @enum {string}
             */
            level: "A" | "B" | "C" | "D" | "E";
            /** Measurement Class */
            measurement_class: string;
            /** Metric Id */
            metric_id: string;
            /** Name */
            name: string;
            /** Unit */
            unit: string;
        };
        /** TacticalQualityView */
        TacticalQualityView: {
            capabilities: components["schemas"]["TacticalCapabilityLevels"];
            /** Dataset Id */
            dataset_id: string;
            /** Disclosure */
            disclosure: string;
            /** Measurement Classes */
            measurement_classes: {
                [key: string]: string;
            };
            /** Quality Evidence */
            quality_evidence: {
                [key: string]: unknown;
            };
            /** Unavailable Reasons */
            unavailable_reasons: string[];
        };
        /** TacticalSeriesMeta */
        TacticalSeriesMeta: {
            /** Algorithm Id */
            algorithm_id: string | null;
            /** Algorithm Version */
            algorithm_version: string | null;
            artifact: components["schemas"]["ArtifactRefView"];
            /** Coordinate Frame Id */
            coordinate_frame_id: string | null;
            /** Display Note */
            display_note: string;
            /** From Ns */
            from_ns: number;
            /** Input Measurement Class */
            input_measurement_class: string | null;
            /**
             * Level
             * @enum {string}
             */
            level: "A" | "B" | "C" | "D" | "E";
            /** Measurement Class */
            measurement_class: string;
            /** Parameters Hash */
            parameters_hash: string | null;
            /** Quality */
            quality: {
                [key: string]: unknown;
            };
            /** Returned Rows */
            returned_rows: number;
            /** Series Name */
            series_name: string;
            /** Source Rows */
            source_rows: number;
            /** To Ns */
            to_ns: number;
        };
        /** TacticalSeriesView */
        TacticalSeriesView: {
            meta: components["schemas"]["TacticalSeriesMeta"];
            /** Rows */
            rows: {
                [key: string]: unknown;
            }[];
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
    artifact_observations_api_artifacts__artifact_id__observations_get: {
        parameters: {
            query?: {
                from_ns?: number | null;
                to_ns?: number | null;
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
                    "application/json": components["schemas"]["EntityObservationView"][];
                };
            };
            /** @description Artifact not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
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
    metric_definitions_api_metrics_definitions_get: {
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
                    "application/json": components["schemas"]["MetricCatalogEntry"][];
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
    ready_api_ready_get: {
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
    tactical_artifacts_api_tactical_artifacts_get: {
        parameters: {
            query: {
                dataset_id: string;
                session_id?: string | null;
                stream_id?: string | null;
                series_name?: string | null;
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
                    "application/json": components["schemas"]["ArtifactRefView"][];
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
    tactical_capabilities_api_tactical_capabilities__dataset_id__get: {
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
                    "application/json": components["schemas"]["TacticalCapabilityView"];
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
    tactical_events_api_tactical_events__artifact_id__get: {
        parameters: {
            query?: {
                from_ns?: number | null;
                to_ns?: number | null;
                max_points?: number | null;
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
                    "application/json": components["schemas"]["TacticalEventPage"];
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
    tactical_methodology_api_tactical_methodology_get: {
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
                    "application/json": components["schemas"]["TacticalMethodologyPage"];
                };
            };
        };
    };
    tactical_quality_api_tactical_quality__dataset_id__get: {
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
                    "application/json": components["schemas"]["TacticalQualityView"];
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
    tactical_series_api_tactical_series__artifact_id__get: {
        parameters: {
            query?: {
                from_ns?: number | null;
                to_ns?: number | null;
                columns?: string | null;
                max_points?: number | null;
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
                    "application/json": components["schemas"]["TacticalSeriesView"];
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
}
