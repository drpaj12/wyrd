-- Mimir store schema version 4 (DDL only, no rows).
-- Source: drpaj12/mimirIII commit b8b4118, mimir/schema.py (V2_DDL, V3_DDL, V4_DDL) and mimir/store.py.
-- Test fixture for Wyrd's Mimir browser; synthetic data is inserted by tests/mimir_fixture.py.
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE records (design TEXT NOT NULL, source TEXT NOT NULL, input_sha256 TEXT NOT NULL, tool_commit TEXT NOT NULL, script_hash TEXT NOT NULL, level TEXT NOT NULL, arch TEXT NOT NULL, seed INTEGER NOT NULL, arm TEXT NOT NULL, family TEXT NOT NULL, metric TEXT NOT NULL, bin TEXT NOT NULL, value REAL NOT NULL, unit TEXT NOT NULL, measurer TEXT NOT NULL, measurer_version TEXT NOT NULL, origin TEXT NOT NULL, PRIMARY KEY (design, source, input_sha256, tool_commit, script_hash, level, arch, seed, arm, family, metric, bin, measurer, origin));
CREATE INDEX records_source_origin ON records(source, origin);
CREATE TABLE design (
        slug TEXT PRIMARY KEY, design_hash TEXT NOT NULL, hash_kind TEXT NOT NULL,
        suite TEXT NOT NULL, name TEXT NOT NULL, origin TEXT NOT NULL);
CREATE INDEX design_hash_idx ON design(design_hash);
CREATE TABLE design_source (
        source TEXT NOT NULL, name TEXT NOT NULL, slug TEXT NOT NULL,
        PRIMARY KEY (source, name));
CREATE TABLE design_meta (
        slug TEXT NOT NULL, field TEXT NOT NULL, value TEXT NOT NULL, source TEXT NOT NULL,
        conf TEXT NOT NULL CHECK (conf IN ('primary', 'secondary', 'inferred', 'missing')), PRIMARY KEY (slug, field));
CREATE TABLE design_lineage (
        slug TEXT NOT NULL, step_no INTEGER NOT NULL, tool TEXT NOT NULL, script TEXT NOT NULL,
        parent_hash TEXT NOT NULL, source TEXT NOT NULL,
        conf TEXT NOT NULL CHECK (conf IN ('primary', 'secondary', 'inferred', 'missing')), PRIMARY KEY (slug, step_no));
CREATE TABLE flow_config (
        config_hash TEXT PRIMARY KEY, name TEXT NOT NULL, config_text_reconstructed TEXT NOT NULL,
        text_kind TEXT NOT NULL CHECK (text_kind IN ('reconstructed', 'recorded-normalised')),
        status TEXT NOT NULL CHECK (status IN ('full', 'partial')), origin TEXT NOT NULL);
CREATE TABLE flow_param (
        config_hash TEXT NOT NULL, step TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
        conf TEXT NOT NULL CHECK (conf IN ('given', 'default', 'default-unrecorded', 'unknown')), source TEXT NOT NULL,
        PRIMARY KEY (config_hash, step, key));
CREATE TABLE run (
        run_id TEXT PRIMARY KEY, slug TEXT NOT NULL, config_hash TEXT NOT NULL,
        source TEXT NOT NULL, design TEXT NOT NULL, arch TEXT NOT NULL, seed INTEGER NOT NULL,
        arm TEXT NOT NULL, family TEXT NOT NULL, tool_commits TEXT NOT NULL, command_line TEXT,
        time_s REAL, peak_rss_mib REAL, host TEXT, origin TEXT NOT NULL,
        tool_commit TEXT NOT NULL DEFAULT '', input_sha256 TEXT NOT NULL DEFAULT '',
        UNIQUE (source, design, arch, seed, arm, config_hash, tool_commit, input_sha256));
CREATE INDEX run_key ON run(source, design, arch, seed, arm);
CREATE TABLE run_artifact (
        run_id TEXT NOT NULL, kind TEXT NOT NULL, blob_sha256 TEXT NOT NULL,
        PRIMARY KEY (run_id, kind));
CREATE TABLE partition (
        partition_id TEXT PRIMARY KEY, algorithm TEXT NOT NULL, algorithm_version TEXT NOT NULL,
        params TEXT NOT NULL, seed INTEGER NOT NULL, slug TEXT NOT NULL, input_hash TEXT NOT NULL,
        n_objects INTEGER NOT NULL, n_clusters INTEGER NOT NULL, assignment_blob TEXT NOT NULL,
        origin TEXT NOT NULL, version_kind TEXT NOT NULL DEFAULT 'recorded',
        dirty INTEGER NOT NULL DEFAULT 0, seed_conf TEXT NOT NULL DEFAULT 'confirmed');
CREATE TABLE analysis_result (
        analysis_id TEXT PRIMARY KEY, algorithm TEXT NOT NULL, params TEXT NOT NULL,
        feature_set_hash TEXT NOT NULL, input_selection TEXT NOT NULL, seed INTEGER NOT NULL,
        script_hash TEXT NOT NULL, script_version TEXT NOT NULL, labels_blob TEXT NOT NULL,
        origin TEXT NOT NULL);
CREATE VIEW record_run AS
        SELECT r.rowid AS record_rowid, u.run_id AS run_id, u.slug AS slug,
               u.config_hash AS config_hash
        FROM records r JOIN run u ON u.source = r.source AND u.design = r.design
             AND u.arch = r.arch AND u.seed = r.seed AND u.arm = r.arm
             AND u.tool_commit = r.tool_commit AND u.input_sha256 = r.input_sha256;
CREATE TABLE structure (
        design TEXT NOT NULL, structure_id TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('adder', 'multiplier', 'shifter', 'equality', 'relational', 'mux', 'register_word', 'counter', 'fsm', 'memory', 'logic', 'unknown')),
        hdl_span TEXT NOT NULL, construct_chain TEXT NOT NULL, label_source TEXT NOT NULL,
        confidence REAL, run_id TEXT NOT NULL, config_hash TEXT NOT NULL,
        granularity TEXT NOT NULL CHECK (granularity IN ('block', 'operator', '')),
        parent_id TEXT NOT NULL, PRIMARY KEY (design, structure_id));
CREATE TABLE structure_mapping (
        design TEXT NOT NULL, structure_id TEXT NOT NULL, run_id TEXT NOT NULL,
        level TEXT NOT NULL CHECK (level IN ('gate', 'lut', 'ble', 'clb', 'placed')), config_hash TEXT NOT NULL,
        n_objects INTEGER NOT NULL, n_pure INTEGER NOT NULL, n_shared INTEGER NOT NULL,
        n_gates INTEGER, n_luts INTEGER, n_carry INTEGER, n_ffs INTEGER, n_bles INTEGER,
        n_clbs INTEGER, n_sites INTEGER, joined_with TEXT NOT NULL, lost_at_pass TEXT NOT NULL,
        bbox_x0 INTEGER, bbox_y0 INTEGER, bbox_x1 INTEGER, bbox_y1 INTEGER, spread REAL,
        crit_share REAL, PRIMARY KEY (design, structure_id, run_id, level));
CREATE TABLE structure_member (
        design TEXT NOT NULL, structure_id TEXT NOT NULL, run_id TEXT NOT NULL,
        atom TEXT NOT NULL, PRIMARY KEY (design, structure_id, run_id, atom));
CREATE INDEX structure_run ON structure(run_id);
CREATE TABLE blob_scrub (
        ref_table TEXT NOT NULL, ref_column TEXT NOT NULL, ref_key TEXT NOT NULL,
        scrubbed_from TEXT NOT NULL, blob_sha256 TEXT NOT NULL,
        PRIMARY KEY (ref_table, ref_column, ref_key));
