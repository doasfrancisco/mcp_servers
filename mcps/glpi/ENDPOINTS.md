# GLPI REST API — Complete GET Endpoints

Verified against `src/Glpi/Api/APIRest.php` (router source code) + `apirest.md` (official docs).
Branch: `11.0/bugfixes` of `glpi-project/glpi`.

Any `:itemtype` is a PHP class inheriting `CommonDBTM`.

---

## A. Session & Config (8 endpoints)

| # | Endpoint | URL | Method |
|---|----------|-----|--------|
| 1 | Init Session | `/initSession` | GET |
| 2 | Kill Session | `/killSession` | GET |
| 3 | Get My Profiles | `/getMyProfiles` | GET |
| 4 | Get Active Profile | `/getActiveProfile` | GET |
| 5 | Get My Entities | `/getMyEntities` | GET |
| 6 | Get Active Entities | `/getActiveEntities` | GET |
| 7 | Get Full Session | `/getFullSession` | GET |
| 8 | Get GLPI Config | `/getGlpiConfig` | GET |

## B. CRUD Read (6 endpoint patterns)

| # | Endpoint | URL Pattern | Method |
|---|----------|-------------|--------|
| 9 | Get an item | `/:itemtype/:id` | GET |
| 10 | Get all items | `/:itemtype/` | GET |
| 11 | Get sub-items | `/:itemtype/:id/:sub_itemtype` | GET |
| 12 | Get multiple items | `/getMultipleItems` | GET |
| 13 | List search options | `/listSearchOptions/:itemtype` | GET |
| 14 | Search items | `/search/:itemtype` | GET |

## C. Massive Actions (2 endpoints)

| # | Endpoint | URL Pattern | Method |
|---|----------|-------------|--------|
| 15 | Get massive actions | `/getMassiveActions/:itemtype[/:id]` | GET |
| 16 | Get massive action params | `/getMassiveActionParameters/:itemtype/:action` | GET |

## D. Special (2 endpoints)

| # | Endpoint | URL Pattern | Method |
|---|----------|-------------|--------|
| 17 | Download document | `/Document/:id` (Accept: application/octet-stream) | GET |
| 18 | User profile picture | `/User/:id/Picture` | GET |

**Total: 18 GET endpoint patterns.**

---

## E. Itemtypes tested in `test_api.py` (22)

| Category | Itemtypes |
|----------|-----------|
| ITIL (3) | Ticket, Problem, Change |
| Assets (7) | Computer, Monitor, NetworkEquipment, Printer, Phone, Peripheral, Software |
| Management (9) | User, Group, Entity, Location, Supplier, Contract, Contact, Document, Budget |
| Config (3) | ITILCategory, Profile, State |

## F. Itemtypes NOT in test script

| Category | Itemtypes |
|----------|-----------|
| ITIL (8) | TicketFollowup, TicketTask, TicketValidation, ITILFollowup, ITILSolution, ProblemTask, ChangeTask, ChangeValidation |
| Assets (11) | CartridgeItem, ConsumableItem, Line, Certificate, Appliance, Cluster, DatabaseInstance, Rack, Enclosure, PDU, PassiveDCEquipment |
| Software (3) | SoftwareVersion, SoftwareLicense, SoftwareCategory |
| Networking (10) | NetworkPort, NetworkName, IPAddress, IPNetwork, VLAN, FQDN, Domain, DomainRecord, DomainRecordType, WifiNetwork |
| Datacenter (4) | Datacenter, DCRoom, Cable, CableType |
| Management (5) | Project, ProjectTask, SLA, OLA, Calendar |
| Tools (6) | Reminder, RSSFeed, KnowbaseItem, SavedSearch, Reservation, ReservationItem |
| Config/Dropdowns (10+) | Manufacturer, ComputerType, ComputerModel, RequestType, SolutionType, TaskCategory, DocumentType, DocumentCategory, ContractType, UserCategory |

## G. Coverage summary

| What | Count | In test_api.py |
|------|-------|----------------|
| GET endpoint patterns | 18 | 4 of 18 (22%) |
| Itemtypes tested | 22 | 22 of ~80+ useful (~27%) |

### Endpoint patterns missing from test

1. getMyProfiles
2. getActiveProfile
3. getMyEntities
4. getActiveEntities
5. getFullSession
6. getGlpiConfig
7. Get single item (`/:itemtype/:id`)
8. Get sub-items (`/:itemtype/:id/:sub_itemtype`)
9. getMultipleItems
10. listSearchOptions
11. getMassiveActions
12. getMassiveActionParameters
13. Document download
14. User profile picture

## H. Useful query parameters

| Parameter | Default | Works on |
|-----------|---------|----------|
| `expand_dropdowns` | false | Get item, Get all, Get sub-items, getMultipleItems |
| `get_hateoas` | true | Get item, Get all, Get sub-items, getMultipleItems |
| `only_id` | false | Get all, Get sub-items |
| `range` | 0-49 | Get all, Get sub-items, Search |
| `sort` | 1 | Get all, Get sub-items, Search |
| `order` | ASC | Get all, Get sub-items, Search |
| `searchText[field]` | NULL | Get all |
| `is_deleted` | false | Get all |
| `with_devices` | — | Get item (Computer, NetworkEquipment, Peripheral, Phone, Printer) |
| `with_disks` | — | Get item (Computer only) |
| `with_softwares` | — | Get item (Computer only) |
| `with_connections` | — | Get item (Computer only) |
| `with_networkports` | — | Get item, Get all |
| `with_infocoms` | — | Get item |
| `with_contracts` | — | Get item |
| `with_documents` | — | Get item |
| `with_tickets` | — | Get item |
| `with_problems` | — | Get item |
| `with_changes` | — | Get item |
| `with_notes` | — | Get item |
| `with_logs` | — | Get item |
| `add_keys_names` | — | Get item, Get all, Get sub-items |
| `get_sha1` | false | Get item, getMultipleItems |
| `raw` | — | listSearchOptions |
| `forcedisplay` | — | Search |
| `criteria` | — | Search |
| `metacriteria` | — | Search (deprecated, use criteria with meta flag) |
| `rawdata` | false | Search |
| `withindexes` | false | Search |
| `uid_cols` | false | Search |
| `giveItems` | false | Search |
