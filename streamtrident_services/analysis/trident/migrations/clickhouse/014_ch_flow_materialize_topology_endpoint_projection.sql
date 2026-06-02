ALTER TABLE ch_flow
    MATERIALIZE PROJECTION IF EXISTS p_topology_endpoint_pair;
