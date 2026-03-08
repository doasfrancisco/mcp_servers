# GLPI MCP — Roadmap

Ordered by priority. Each phase builds on the previous one.

## Phase 1 — Session & tickets (DONE)

- [x] Session management with token caching
- [x] Auto-refresh on 401
- [x] `glpi_tickets_today` — quick daily overview
- [x] `glpi_search` — generic search with criteria
- [x] `glpi_get_item` — single item by ID
- [x] `glpi_get_items` — list items paginated
- [x] `glpi_get_sub_items` — related items (followups, tasks, etc.)
- [x] `glpi_list_search_options` — discover searchable fields
- [x] Session/config tools (profiles, entities, full session, config)

## Phase 2 — Ticket deep-dive

- [ ] `glpi_get_ticket_timeline` — combine followups + tasks + solutions in chronological order
- [ ] `glpi_search_tickets` — convenience wrapper with date, status, category, assignee filters
- [ ] `glpi_get_ticket_stats` — count by status, category, or assignee for a date range

## Phase 3 — Assets

- [ ] `glpi_search_computers` — convenience wrapper for computer search
- [ ] `glpi_get_computer_full` — computer with software, devices, disks, network in one call
- [ ] `glpi_get_network_info` — network ports, IPs, VLANs for an item
- [ ] Expose remaining asset types: Monitor, NetworkEquipment, Printer, Phone, Peripheral, Software

## Phase 4 — Management & users

- [ ] `glpi_search_users` — find users by name, email, or group
- [ ] `glpi_get_user_tickets` — all tickets assigned to or opened by a user
- [ ] `glpi_list_groups` — groups with member counts
- [ ] `glpi_list_suppliers` — supplier directory
- [ ] `glpi_list_contracts` — active contracts with expiration dates
- [ ] `glpi_list_projects` — project overview with task counts

## Phase 5 — Knowledge base & tools

- [ ] `glpi_search_knowbase` — search knowledge base articles
- [ ] `glpi_get_knowbase_article` — full article content
- [ ] `glpi_list_reminders` — active reminders
- [ ] `glpi_list_saved_searches` — reuse saved GLPI searches

## Phase 6 — Configuration & dropdowns

- [ ] `glpi_list_categories` — ITIL categories tree
- [ ] `glpi_list_locations` — location hierarchy
- [ ] `glpi_list_states` — asset lifecycle states
- [ ] `glpi_list_sla_ola` — SLA/OLA definitions with target times
- [ ] `glpi_list_calendars` — business calendars and holidays

## Phase 7 — Advanced

- [ ] `glpi_download_document` — download attached files
- [ ] `glpi_get_massive_actions` — list available bulk operations
- [ ] `glpi_get_user_picture` — profile pictures
- [ ] Profile/entity switching tools
- [ ] Batch operations via getMultipleItems

## Phase 8 — Write operations (maybe)

Unlikely to be needed, but documented for completeness.

- [ ] `glpi_create_ticket` — create a new ticket
- [ ] `glpi_update_ticket` — update ticket fields (status, assignee, category)
- [ ] `glpi_add_followup` — add a followup to a ticket
- [ ] `glpi_add_task` — add a task to a ticket
- [ ] `glpi_add_solution` — propose a solution
- [ ] `glpi_assign_ticket` — assign ticket to user or group
