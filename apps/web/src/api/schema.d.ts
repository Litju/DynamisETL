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
    "/api/basketball/contests/{contest_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Basketball Spatial Game */
        get: operations["basketball_spatial_game_api_basketball_contests__contest_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/basketball/contests/{contest_id}/events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Basketball Events */
        get: operations["basketball_events_api_basketball_contests__contest_id__events_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/basketball/contests/{contest_id}/frames": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Basketball Frames */
        get: operations["basketball_frames_api_basketball_contests__contest_id__frames_get"];
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
    "/api/catalog/source-capabilities": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Source Capabilities */
        get: operations["source_capabilities_api_catalog_source_capabilities_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/catalog/sports/matches": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Sports Catalog Matches */
        get: operations["sports_catalog_matches_api_catalog_sports_matches_get"];
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
    "/api/games": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Games */
        get: operations["games_api_games_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/games/editions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Game Editions */
        get: operations["game_editions_api_games_editions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/games/{contest_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Game */
        get: operations["game_api_games__contest_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/games/{contest_id}/box": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Game Box */
        get: operations["game_box_api_games__contest_id__box_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/games/{contest_id}/plays": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Game Plays */
        get: operations["game_plays_api_games__contest_id__plays_get"];
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
    "/api/pose/range-report": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Pose Range Report */
        get: operations["pose_range_report_api_pose_range_report_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/processing/artifacts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Processing Artifacts */
        get: operations["processing_artifacts_api_processing_artifacts_get"];
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
    "/api/season/editions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Season Editions */
        get: operations["season_editions_api_season_editions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/season/editions/{edition_id}/families/{family}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Season Family */
        get: operations["season_family_api_season_editions__edition_id__families__family__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/season/editions/{edition_id}/families/{family}/profile": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Season Profile */
        get: operations["season_profile_api_season_editions__edition_id__families__family__profile_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/season/editions/{edition_id}/families/{family}/rows": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Season Rows */
        get: operations["season_rows_api_season_editions__edition_id__families__family__rows_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/season/editions/{edition_id}/links": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Season Player Links */
        get: operations["season_player_links_api_season_editions__edition_id__links_get"];
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
        /** BasketballBallPointView */
        BasketballBallPointView: {
            /** Is Detected */
            is_detected: boolean | null;
            /** X */
            x: number;
            /** Y */
            y: number;
            /** Z */
            z: number | null;
        };
        /** BasketballEventPage */
        BasketballEventPage: {
            /** Contest Id */
            contest_id: string;
            /** Limit */
            limit: number;
            /** Offset */
            offset: number;
            /** Period */
            period: number | null;
            /** Rows */
            rows: components["schemas"]["BasketballEventView"][];
            /** Total */
            total: number;
        };
        /** BasketballEventView */
        BasketballEventView: {
            /** Attributes */
            attributes: {
                [key: string]: unknown;
            };
            /** Canonical Time Ns */
            canonical_time_ns: number | null;
            /** Contest Period Id */
            contest_period_id: string;
            /** Location */
            location: {
                [key: string]: number | null;
            } | null;
            /** Provider Event Type */
            provider_event_type: string;
            /** Sequence Index */
            sequence_index: string;
            /** Source Clock */
            source_clock: {
                [key: string]: unknown;
            } | null;
            /** Source Event Id */
            source_event_id: string;
            /** Subject Id */
            subject_id: string | null;
            /** Team Id */
            team_id: string | null;
        };
        /** BasketballFramePage */
        BasketballFramePage: {
            /** Contest Id */
            contest_id: string;
            /** From Frame */
            from_frame: number;
            /** Limit */
            limit: number;
            /** Period */
            period: number;
            /** Rows */
            rows: components["schemas"]["BasketballFrameView"][];
            /** Total Frames */
            total_frames: number;
        };
        /** BasketballFrameView */
        BasketballFrameView: {
            ball: components["schemas"]["BasketballBallPointView"] | null;
            /** Ball Present */
            ball_present: boolean;
            /** Canonical Time Ns */
            canonical_time_ns: number;
            /** Frame Idx */
            frame_idx: number;
            /** Game Clock S */
            game_clock_s: number | null;
            /** Game Clock Stopped */
            game_clock_stopped: boolean;
            /** Is Dead Time */
            is_dead_time: boolean;
            /** Period Number */
            period_number: number;
            /** Player Count */
            player_count: number;
            /** Players */
            players: components["schemas"]["BasketballPlayerPointView"][];
            /** Shot Clock S */
            shot_clock_s: number | null;
            /** Wall Clock Ms */
            wall_clock_ms: number;
        };
        /** BasketballPeriodRangeView */
        BasketballPeriodRangeView: {
            /** Dead Time Frames */
            dead_time_frames: number;
            /** First Active Frame */
            first_active_frame: number;
            /** First Frame */
            first_frame: number;
            /** Frame Count */
            frame_count: number;
            /** Label */
            label: string;
            /** Last Frame */
            last_frame: number;
            /** Number */
            number: number;
        };
        /** BasketballPlayerPointView */
        BasketballPlayerPointView: {
            /** Display Name */
            display_name: string;
            /** Is Detected */
            is_detected: boolean | null;
            /** Jersey */
            jersey: string | null;
            /** Provider Player Id */
            provider_player_id: string;
            /** Subject Id */
            subject_id: string;
            /** Team Id */
            team_id: string | null;
            /** X */
            x: number;
            /** Y */
            y: number;
            /** Z */
            z: number | null;
        };
        /** BasketballRosterPlayerView */
        BasketballRosterPlayerView: {
            /** Display Name */
            display_name: string;
            /** Jersey */
            jersey: string | null;
            /** Provider Player Id */
            provider_player_id: string;
            /** Subject Id */
            subject_id: string;
            /** Team Id */
            team_id: string | null;
            /** Team Name */
            team_name: string | null;
        };
        /** BasketballSpatialGameView */
        BasketballSpatialGameView: {
            /** Axis Orientation */
            axis_orientation: {
                [key: string]: string;
            };
            /** Court Dimensions */
            court_dimensions: {
                [key: string]: number;
            };
            /** Dataset Id */
            dataset_id: string;
            /** Events Materialized */
            events_materialized: boolean;
            /** Frame Rate Hz */
            frame_rate_hz: number;
            game: components["schemas"]["GameDetailView"];
            /** Origin */
            origin: {
                [key: string]: number;
            };
            /** Periods */
            periods: components["schemas"]["BasketballPeriodRangeView"][];
            /** Players */
            players: components["schemas"]["BasketballRosterPlayerView"][];
            /** Source Revision */
            source_revision: string;
            /** Spatial Reference Id */
            spatial_reference_id: string;
            /** Tracking Materialized */
            tracking_materialized: boolean;
            /** Units */
            units: string;
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
            /**
             * Ingested Modalities
             * @default []
             */
            ingested_modalities: string[];
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
            /**
             * Ingested Modalities
             * @default []
             */
            ingested_modalities: string[];
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
        /** GameBoxFamilyView */
        GameBoxFamilyView: {
            /** Artifact Id */
            artifact_id: string;
            /** Columns */
            columns: string[];
            /** Family */
            family: string;
            /** Grain Kind */
            grain_kind: string;
            /** Rows */
            rows: {
                [key: string]: unknown;
            }[];
        };
        /** GameBoxView */
        GameBoxView: {
            /** Contest Id */
            contest_id: string;
            /** Families */
            families: components["schemas"]["GameBoxFamilyView"][];
            /**
             * Grain
             * @enum {string}
             */
            grain: "player" | "team";
        };
        /** GameDetailView */
        GameDetailView: {
            edition: components["schemas"]["GameEditionView"];
            /** Periods */
            periods: components["schemas"]["GamePeriodView"][];
            /** Subjects */
            subjects: {
                [key: string]: string;
            };
            summary: components["schemas"]["GameSummaryView"];
            /** Teams By Id */
            teams_by_id: {
                [key: string]: string;
            };
        };
        /**
         * GameEditionView
         * @description A competition edition that owns discrete game-grain data.
         */
        GameEditionView: {
            /** Clock Mapping Ids */
            clock_mapping_ids?: string[];
            /** Competition Id */
            competition_id: string;
            /** Competition Name */
            competition_name: string;
            /** Completed Count */
            completed_count: number;
            /** Contest Count */
            contest_count: number;
            /** Dataset Id */
            dataset_id: string;
            /** Edition Id */
            edition_id: string;
            /** Edition Label */
            edition_label: string;
            /** Ends On */
            ends_on: string | null;
            /** Families */
            families: components["schemas"]["GameFamilyRef"][];
            /** League Id */
            league_id: string | null;
            license: components["schemas"]["LicenseView"];
            /** Measurement Class */
            measurement_class: string;
            /** Provider */
            provider: string;
            /** Score Reconciliation */
            score_reconciliation?: {
                [key: string]: unknown;
            };
            /** Sport Id */
            sport_id: string;
            /** Sport Name */
            sport_name: string;
            /** Starts On */
            starts_on: string | null;
        };
        /** GameFamilyRef */
        GameFamilyRef: {
            /** Artifact Id */
            artifact_id: string;
            /** Artifact Type */
            artifact_type: string;
            /** Checksum Sha256 */
            checksum_sha256: string;
            /** Family */
            family: string;
            /** Freshness */
            freshness?: {
                [key: string]: unknown;
            };
            /** Grain Kind */
            grain_kind: string;
            /** Release Asset Id */
            release_asset_id: number | null;
            /** Release Tag */
            release_tag: string | null;
            /** Row Count */
            row_count: number;
            /** Run Id */
            run_id: string | null;
            /** Snapshot */
            snapshot: string | null;
            /** Source File Key */
            source_file_key: string | null;
        };
        /** GamePage */
        GamePage: {
            /** Limit */
            limit: number;
            /** Offset */
            offset: number;
            /** Rows */
            rows: components["schemas"]["GameSummaryView"][];
            /** Total */
            total: number;
        };
        /** GamePeriodView */
        GamePeriodView: {
            /** Contest Period Id */
            contest_period_id: string;
            /** End Ns */
            end_ns: number | null;
            /** Event Count */
            event_count: number;
            /** Kind */
            kind: string;
            /** Label */
            label: string | null;
            /** Number */
            number: number;
            /** Start Ns */
            start_ns: number | null;
        };
        /** GamePlayPage */
        GamePlayPage: {
            /** Contest Id */
            contest_id: string;
            /** Limit */
            limit: number;
            /** Offset */
            offset: number;
            /** Period */
            period: number | null;
            /** Rows */
            rows: components["schemas"]["GamePlayView"][];
            /** Total */
            total: number;
        };
        /** GamePlayView */
        GamePlayView: {
            /** Attributes */
            attributes: {
                [key: string]: unknown;
            };
            /** Attributes Schema Id */
            attributes_schema_id: string;
            /** Attributes Schema Version */
            attributes_schema_version: string;
            /** Canonical Time Ns */
            canonical_time_ns: number | null;
            /** Contest Period Id */
            contest_period_id: string;
            /** Period Number */
            period_number: number;
            /** Provider Event Type */
            provider_event_type: string;
            /** Sequence Index */
            sequence_index: string;
            /** Source */
            source?: {
                [key: string]: unknown;
            };
            /** Source Clock */
            source_clock: {
                [key: string]: unknown;
            } | null;
            /** Source Event Id */
            source_event_id: string;
            /** Subject Id */
            subject_id: string | null;
            /** Team Id */
            team_id: string | null;
        };
        /** GameSummaryView */
        GameSummaryView: {
            /** Actual Start At */
            actual_start_at: string | null;
            /** Completed */
            completed: boolean;
            /** Contest Id */
            contest_id: string;
            /** Edition Id */
            edition_id: string | null;
            /** Period Count */
            period_count: number;
            /** Play By Play Available */
            play_by_play_available: boolean;
            /** Postseason */
            postseason: boolean;
            /** Provider Game Id */
            provider_game_id: string | null;
            /** Scheduled Start At */
            scheduled_start_at: string | null;
            /** Sport Id */
            sport_id: string;
            /** Status */
            status: string | null;
            /** Teams */
            teams: components["schemas"]["GameTeamView"][];
            /** Venue */
            venue: string | null;
        };
        /** GameTeamView */
        GameTeamView: {
            /** Display Name */
            display_name: string;
            /** Score */
            score: number | null;
            /** Side */
            side: string;
            /** Team Id */
            team_id: string;
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
        /** PitchDimensionsView */
        PitchDimensionsView: {
            /** Length M */
            length_m: number;
            /** Width M */
            width_m: number;
        };
        /** PoseRangeMetricView */
        PoseRangeMetricView: {
            /** Description */
            description: string;
            /** Metric Id */
            metric_id: string;
            /** Metric Name */
            metric_name: string;
            /** Provenance */
            provenance: {
                [key: string]: unknown;
            };
            /** Si Unit */
            si_unit: string;
            /** Value Num */
            value_num: number;
        };
        /** PoseRangeReportView */
        PoseRangeReportView: {
            /** Algorithm Id */
            algorithm_id: string;
            /** Algorithm Version */
            algorithm_version: string;
            /** Code Git Sha */
            code_git_sha: string | null;
            /** Dataset Id */
            dataset_id: string;
            /** Display Note */
            display_note: string;
            /** From Ns */
            from_ns: number;
            /** Input Artifact Checksums */
            input_artifact_checksums: {
                [key: string]: string;
            };
            /** Metrics */
            metrics: components["schemas"]["PoseRangeMetricView"][];
            /** Parameters Hash */
            parameters_hash: string;
            /** Session Id */
            session_id: string;
            /** Stream Id */
            stream_id: string;
            /** Subject Id */
            subject_id: string;
            /** To Ns */
            to_ns: number;
            /** Trial Id */
            trial_id: string;
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
        /** SeasonContestLinkView */
        SeasonContestLinkView: {
            /** Contest Id */
            contest_id: string;
            /** Dataset Id */
            dataset_id: string;
            /** Session Id */
            session_id: string;
        };
        /**
         * SeasonEditionView
         * @description A competition edition that owns season-grain data, with its provenance.
         */
        SeasonEditionView: {
            /** Competition Id */
            competition_id: string;
            /** Competition Name */
            competition_name: string;
            /** Dataset Id */
            dataset_id: string;
            /** Edition Id */
            edition_id: string;
            /** Edition Label */
            edition_label: string;
            /** Families */
            families: components["schemas"]["SeasonFamilyRef"][];
            /** Glossary Url */
            glossary_url: string | null;
            /** Inclusion Rule */
            inclusion_rule: string;
            license: components["schemas"]["LicenseView"];
            /** Measurement Class */
            measurement_class: string;
            /** Provider */
            provider: string;
            /** Registry Version */
            registry_version: string;
            /** Sport Id */
            sport_id: string;
            /** Sport Name */
            sport_name: string;
        };
        /**
         * SeasonFamilyRef
         * @description One provider aggregate family materialized for a competition edition.
         */
        SeasonFamilyRef: {
            /** Artifact Id */
            artifact_id: string;
            /** Checksum Sha256 */
            checksum_sha256: string;
            /** Family */
            family: string;
            /** Grain Axes */
            grain_axes: string[];
            /** Grain Kind */
            grain_kind: string;
            /** Label */
            label: string;
            /** Match Count Column */
            match_count_column: string;
            /** Row Count */
            row_count: number;
            /** Run Id */
            run_id: string | null;
            /** Source File Key */
            source_file_key: string | null;
            /** Source Population Rows */
            source_population_rows: number | null;
            /** Source Revision */
            source_revision: string | null;
        };
        /**
         * SeasonFamilyView
         * @description Family metadata: metric registry and population facets. No metric values.
         */
        SeasonFamilyView: {
            edition: components["schemas"]["SeasonEditionView"];
            family: components["schemas"]["SeasonFamilyRef"];
            /** Metrics */
            metrics: components["schemas"]["SeasonMetricView"][];
            /** Population Rows */
            population_rows: number;
            /** Population Subjects */
            population_subjects: number;
            /** Position Groups */
            position_groups: components["schemas"]["SeasonPositionView"][];
            /** Teams */
            teams: components["schemas"]["SeasonTeamView"][];
        };
        /** SeasonMetricView */
        SeasonMetricView: {
            /** Base */
            base: string | null;
            /** Basis */
            basis: string;
            /** Column */
            column: string;
            /** Definition */
            definition: string;
            /** Exposure */
            exposure: boolean;
            /** Family */
            family: string;
            /** Group */
            group: string;
            /**
             * Higher Is
             * @enum {string}
             */
            higher_is: "more" | "faster" | "neutral";
            /** Label */
            label: string;
            /** Metric Id */
            metric_id: string;
            /** Split */
            split: string | null;
            /** Unit */
            unit: string;
        };
        /**
         * SeasonPlayerLinksView
         * @description Contests linked to a season subject through the provider identity crosswalk.
         */
        SeasonPlayerLinksView: {
            /** Appearances */
            appearances: components["schemas"]["SeasonContestLinkView"][];
            /** Identity Authority */
            identity_authority: string;
            /** Provider Namespace */
            provider_namespace: string | null;
            /** Provider Player Ids */
            provider_player_ids: string[];
            /** Subject Id */
            subject_id: string;
            /** Team Contest Ids */
            team_contest_ids: string[];
        };
        /**
         * SeasonPopulationView
         * @description The explicit denominator every rank/percentile is relative to.
         */
        SeasonPopulationView: {
            /** Label */
            label: string;
            /** Min Matches */
            min_matches: number | null;
            /** Position Group */
            position_group: string | null;
            /** Rows */
            rows: number;
            /**
             * Scope
             * @enum {string}
             */
            scope: "edition" | "position" | "team";
            /** Selected Row In Population */
            selected_row_in_population: boolean;
            /** Team Id */
            team_id: string | null;
            /** Unit Of Analysis */
            unit_of_analysis: string;
        };
        /** SeasonPositionView */
        SeasonPositionView: {
            /** Position Group */
            position_group: string;
            /** Rows */
            rows: number;
        };
        /**
         * SeasonProfileView
         * @description Reproducible season profile: context, values, denominator and provenance.
         */
        SeasonProfileView: {
            /** Caveats */
            caveats: string[];
            edition: components["schemas"]["SeasonEditionView"];
            family: components["schemas"]["SeasonFamilyRef"];
            /** Metrics */
            metrics: components["schemas"]["SeasonRankedMetricView"][];
            /** Percentile Method */
            percentile_method: string;
            population: components["schemas"]["SeasonPopulationView"];
            /** Rank Method */
            rank_method: string;
            row: components["schemas"]["SeasonRowView"];
        };
        /** SeasonRankedMetricView */
        SeasonRankedMetricView: {
            /** Column */
            column: string;
            /** Metric Id */
            metric_id: string;
            /** Percentile */
            percentile: number | null;
            /** Population Maximum */
            population_maximum: number | null;
            /** Population Median */
            population_median: number | null;
            /** Population Minimum */
            population_minimum: number | null;
            /** Rank */
            rank: number | null;
            /** Valid N */
            valid_n: number;
            /** Value */
            value: number | null;
        };
        /** SeasonRowPage */
        SeasonRowPage: {
            /** Limit */
            limit: number;
            /** Metrics */
            metrics: string[];
            /** Offset */
            offset: number;
            /** Rows */
            rows: components["schemas"]["SeasonRowView"][];
            /** Total */
            total: number;
        };
        /**
         * SeasonRowView
         * @description One grain row: subject × team × edition × position group.
         */
        SeasonRowView: {
            /** Matches */
            matches: number | null;
            /** Player Name */
            player_name: string;
            /** Player Short Name */
            player_short_name: string | null;
            /** Position Group */
            position_group: string;
            /** Subject Id */
            subject_id: string;
            /** Team Id */
            team_id: string;
            /** Team Name */
            team_name: string;
            /** Values */
            values: {
                [key: string]: number | null;
            };
        };
        /** SeasonTeamView */
        SeasonTeamView: {
            /** Display Name */
            display_name: string;
            /** Rows */
            rows: number;
            /** Team Id */
            team_id: string;
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
        /** SourceCapabilityView */
        SourceCapabilityView: {
            /** Availability State */
            availability_state: string;
            /** Entry Id */
            entry_id: string;
            /** External Id */
            external_id: string;
            /** Local Capabilities */
            local_capabilities: string[];
            /** Local Readiness */
            local_readiness: string;
            /** Object Kind */
            object_kind: string;
            /** Pending Local Capabilities */
            pending_local_capabilities: string[];
            /** Provider Metadata */
            provider_metadata: {
                [key: string]: unknown;
            };
            /** Source File States */
            source_file_states: {
                [key: string]: string;
            };
            /** Source Readiness */
            source_readiness: string;
            /** Upstream Capabilities */
            upstream_capabilities: string[];
        };
        /**
         * SportsCatalogMatchView
         * @description Metadata-only contest entry from the normalized sports and source catalogs.
         */
        SportsCatalogMatchView: {
            /** Actual Start At */
            actual_start_at: string | null;
            /** Competition Id */
            competition_id: string | null;
            /** Competition Name */
            competition_name: string | null;
            /** Contest Id */
            contest_id: string;
            /** Dataset Id */
            dataset_id: string;
            /** Edition Id */
            edition_id: string | null;
            /** Edition Label */
            edition_label: string | null;
            /** Home Away Supported */
            home_away_supported: boolean;
            /** Label */
            label: string | null;
            /** Periods */
            periods: components["schemas"]["SportsCatalogPeriodView"][];
            /** Provider Match Id */
            provider_match_id: string;
            /** Scheduled Start At */
            scheduled_start_at: string | null;
            /** Session Id */
            session_id: string | null;
            source_capability?: components["schemas"]["SourceCapabilityView"] | null;
            /** Sport Code */
            sport_code: string;
            /** Sport Id */
            sport_id: string;
            /** Sport Name */
            sport_name: string;
            /** Teams */
            teams: components["schemas"]["SportsCatalogTeamView"][];
            /** Venue */
            venue: string | null;
        };
        /** SportsCatalogPeriodView */
        SportsCatalogPeriodView: {
            /** Contest Period Id */
            contest_period_id: string;
            /** End Ns */
            end_ns: number | null;
            /** Kind */
            kind: string;
            /** Label */
            label: string | null;
            /** Source Period Number */
            source_period_number: string;
            /** Start Ns */
            start_ns: number | null;
        };
        /** SportsCatalogTeamView */
        SportsCatalogTeamView: {
            /** Display Name */
            display_name: string;
            /** Score */
            score: number | null;
            /** Side */
            side: string;
            /** Team Id */
            team_id: string;
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
            pitch_dimensions_m?: components["schemas"]["PitchDimensionsView"] | null;
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
            /** Matchlab V3 Functional Units */
            matchlab_v3_functional_units: string;
            /** Matchlab V3 Interactions */
            matchlab_v3_interactions: string;
            /** Matchlab V3 Shape Graph */
            matchlab_v3_shape_graph: string;
            /** Matchlab V3 Triangles */
            matchlab_v3_triangles: string;
            /** Possession Context */
            possession_context: string;
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
            level: "A" | "B" | "C" | "D" | "E" | "V3";
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
            level: "A" | "B" | "C" | "D" | "E" | "V3";
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
    basketball_spatial_game_api_basketball_contests__contest_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                contest_id: string;
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
                    "application/json": components["schemas"]["BasketballSpatialGameView"];
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
    basketball_events_api_basketball_contests__contest_id__events_get: {
        parameters: {
            query?: {
                period?: number | null;
                limit?: number;
                offset?: number;
            };
            header?: never;
            path: {
                contest_id: string;
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
                    "application/json": components["schemas"]["BasketballEventPage"];
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
    basketball_frames_api_basketball_contests__contest_id__frames_get: {
        parameters: {
            query: {
                period: number;
                from_frame?: number;
                limit?: number;
            };
            header?: never;
            path: {
                contest_id: string;
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
                    "application/json": components["schemas"]["BasketballFramePage"];
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
    source_capabilities_api_catalog_source_capabilities_get: {
        parameters: {
            query: {
                dataset_id: string;
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
                    "application/json": components["schemas"]["SourceCapabilityView"][];
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
    sports_catalog_matches_api_catalog_sports_matches_get: {
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
                    "application/json": components["schemas"]["SportsCatalogMatchView"][];
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
    games_api_games_get: {
        parameters: {
            query: {
                edition_id: string;
                team_id?: string | null;
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
                    "application/json": components["schemas"]["GamePage"];
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
    game_editions_api_games_editions_get: {
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
                    "application/json": components["schemas"]["GameEditionView"][];
                };
            };
        };
    };
    game_api_games__contest_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                contest_id: string;
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
                    "application/json": components["schemas"]["GameDetailView"];
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
    game_box_api_games__contest_id__box_get: {
        parameters: {
            query?: {
                grain?: "player" | "team";
            };
            header?: never;
            path: {
                contest_id: string;
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
                    "application/json": components["schemas"]["GameBoxView"];
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
    game_plays_api_games__contest_id__plays_get: {
        parameters: {
            query?: {
                period?: number | null;
                limit?: number;
                offset?: number;
                /** @description Comma-separated preserved provider columns */
                source_columns?: string | null;
            };
            header?: never;
            path: {
                contest_id: string;
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
                    "application/json": components["schemas"]["GamePlayPage"];
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
    pose_range_report_api_pose_range_report_get: {
        parameters: {
            query: {
                dataset_id: string;
                session_id: string;
                stream_id: string;
                subject_id: string;
                from_ns: number;
                to_ns: number;
                landmark_name: string;
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
                    "application/json": components["schemas"]["PoseRangeReportView"];
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
    processing_artifacts_api_processing_artifacts_get: {
        parameters: {
            query: {
                dataset_id: string;
                session_id?: string | null;
                stream_id?: string | null;
                algorithm_id?: string | null;
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
    season_editions_api_season_editions_get: {
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
                    "application/json": components["schemas"]["SeasonEditionView"][];
                };
            };
        };
    };
    season_family_api_season_editions__edition_id__families__family__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                edition_id: string;
                family: string;
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
                    "application/json": components["schemas"]["SeasonFamilyView"];
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
    season_profile_api_season_editions__edition_id__families__family__profile_get: {
        parameters: {
            query: {
                subject_id: string;
                team_id?: string | null;
                position_group?: string | null;
                population?: "edition" | "position" | "team";
                min_matches?: number | null;
                /** @description Comma-separated metric columns */
                metrics?: string | null;
                /** @description Rank against this team's rows instead of the row's own */
                population_team_id?: string | null;
                /** @description Rank against this position group instead of the row's own */
                population_position_group?: string | null;
            };
            header?: never;
            path: {
                edition_id: string;
                family: string;
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
                    "application/json": components["schemas"]["SeasonProfileView"];
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
    season_rows_api_season_editions__edition_id__families__family__rows_get: {
        parameters: {
            query?: {
                /** @description Comma-separated metric columns */
                metrics?: string | null;
                team_id?: string | null;
                position_group?: string | null;
                subject_id?: string[] | null;
                min_matches?: number | null;
                limit?: number;
                offset?: number;
            };
            header?: never;
            path: {
                edition_id: string;
                family: string;
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
                    "application/json": components["schemas"]["SeasonRowPage"];
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
    season_player_links_api_season_editions__edition_id__links_get: {
        parameters: {
            query: {
                subject_id: string;
            };
            header?: never;
            path: {
                edition_id: string;
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
                    "application/json": components["schemas"]["SeasonPlayerLinksView"];
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
