-- Section 04C read-only reader permissions. No mutation rights.
grant select on gs_streamlit_v1.reconciliation_evidence_sources,
                gs_streamlit_v1.reconciliation_decision_events,
                gs_streamlit_v1.reconciliation_movement_links
to gs_streamlit_v1_reader;

create policy "gs_streamlit_reader_can_read_evidence_sources"
on gs_streamlit_v1.reconciliation_evidence_sources
for select to gs_streamlit_v1_reader using (true);

create policy "gs_streamlit_reader_can_read_decision_events"
on gs_streamlit_v1.reconciliation_decision_events
for select to gs_streamlit_v1_reader using (true);

create policy "gs_streamlit_reader_can_read_movement_links"
on gs_streamlit_v1.reconciliation_movement_links
for select to gs_streamlit_v1_reader using (true);
