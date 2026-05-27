# RBAC Permissions Summary Report
## AdventureWorksLT2019 Database

Generated: 2026-05-26
Database: AdventureWorksLT2019
Roles: 5 (customer, sales, admin, analyst, support)
Total SalesLT Tables: 10

---

## PERMISSIONS MATRIX

| Role | Total Tables | Unrestricted | Filtered | Denied | Total Columns (Allowed) |
|------|-------------|--------------|----------|--------|------------------------|
| **customer** | 6 | 2 | 4 | 4 | 41 |
| **sales** | 10 | 9 | 1 | 0 | 89 |
| **admin** | 10 | 10 | 0 | 0 | 100+ |
| **analyst** | 6 | 5 | 1 | 4 | 54 |
| **support** | 3 | 1 | 2 | 7 | 16 |

---

## DETAILED BREAKDOWN BY ROLE

### 1. CUSTOMER ROLE
**Purpose:** Self-service customers - access own data only

**Tables Accessible (6 / 10):**

| Table | Access Type | Filter Columns | Read Columns | Security Notes |
|-------|------------|----------------|--------------|-----------------|
| SalesLT.Customer | Filtered | CustomerID (id) | 10: NameStyle, Title, FirstName, MiddleName, LastName, Suffix, CompanyName, EmailAddress, Phone | ✓ Excludes: PasswordHash, PasswordSalt, SalesPerson, rowguid, ModifiedDate |
| SalesLT.SalesOrderHeader | Filtered | CustomerID (id), Status (enum: 1-6) | 10: SalesOrderID, RevisionNumber, OrderDate, DueDate, ShipDate, OnlineOrderFlag, SalesOrderNumber, PurchaseOrderNumber, ShipMethod | ✓ Excludes: Pricing (SubTotal, TaxAmt, Freight, TotalDue), CreditCardApprovalCode |
| SalesLT.SalesOrderDetail | Filtered | SalesOrderID (id) | 7: SalesOrderDetailID, OrderQty, ProductID, UnitPrice, UnitPriceDiscount, LineTotal | ✓ Transparent on line pricing |
| SalesLT.Product | Unrestricted | — | All | Full product catalog for shopping/discovery |
| SalesLT.ProductCategory | Unrestricted | — | All | Navigation and browsing |
| SalesLT.CustomerAddress | Filtered | CustomerID (id) | 3: AddressID, AddressType | ✓ Own address associations only |

**Denied Tables (4):**
- SalesLT.ProductDescription (detail not needed for customers)
- SalesLT.ProductModel (detail not needed)
- SalesLT.ProductModelProductDescription (internal)
- SalesLT.Address (use CustomerAddress instead)

**Total Columns:** 41 readable columns across 6 tables

**Key Security Principles:**
- ✓ All filters enforce user's own data (CustomerID)
- ✓ No access to authentication credentials (PasswordHash, PasswordSalt)
- ✓ No access to payment info (CreditCardApprovalCode)
- ✓ Cannot see other customers' data
- ✓ No system metadata (rowguid, ModifiedDate)

---

### 2. SALES ROLE
**Purpose:** Sales team - full business access, no auth PII

**Tables Accessible (10 / 10):**

| Table | Access Type | Filter Columns | Security Notes |
|-------|------------|----------------|-----------------|
| SalesLT.Customer | Filtered | None (full) | ✓ Excludes: PasswordHash, PasswordSalt (auth secrets) |
| SalesLT.SalesOrderHeader | Unrestricted | None | Full order + financial data for order management |
| SalesLT.SalesOrderDetail | Unrestricted | None | Line items with pricing and discounts |
| SalesLT.Product | Unrestricted | None | Catalog for quotes |
| SalesLT.ProductCategory | Unrestricted | None | Category browsing |
| SalesLT.ProductDescription | Unrestricted | None | Product details for customers |
| SalesLT.ProductModel | Unrestricted | None | Specifications |
| SalesLT.ProductModelProductDescription | Unrestricted | None | Multilingual support |
| SalesLT.Address | Unrestricted | None | Shipping/billing validation |
| SalesLT.CustomerAddress | Unrestricted | None | Address type mapping |

**Total Columns:** 89 readable columns (10 columns blocked: PasswordHash, PasswordSalt, etc.)

**Key Security Principles:**
- ✓ Full business visibility for order management and forecasting
- ✓ Excluded: Authentication credentials (PasswordHash, PasswordSalt)
- ✓ Included: All pricing, discounts, and customer data
- ✓ Role-based without row-level restrictions (sales manages all territories)

---

### 3. ADMIN ROLE
**Purpose:** Database administrators - unrestricted access

**Tables Accessible (10 / 10):**
- ✓ SalesLT.Customer (all columns including PasswordHash, PasswordSalt)
- ✓ SalesLT.SalesOrderHeader (all columns including payment data)
- ✓ SalesLT.SalesOrderDetail (all columns)
- ✓ SalesLT.Product (all columns)
- ✓ SalesLT.ProductCategory (all columns)
- ✓ SalesLT.ProductDescription (all columns)
- ✓ SalesLT.ProductModel (all columns)
- ✓ SalesLT.ProductModelProductDescription (all columns)
- ✓ SalesLT.Address (all columns)
- ✓ SalesLT.CustomerAddress (all columns)

**Total Columns:** 100+ (all columns accessible)

**Key Security Principles:**
- ✓ No filters applied (full access for audits, maintenance, backups, security remediation)
- ✓ Can perform DDL/DML operations as needed
- ✓ Can access encrypted or sensitive fields for administration
- ✓ Full audit trail access via ModifiedDate, rowguid

---

### 4. ANALYST ROLE
**Purpose:** Business analysts - read-only aggregate/non-PII data

**Tables Accessible (6 / 10):**

| Table | Access Type | Filter Columns | Security Notes |
|-------|------------|----------------|-----------------|
| SalesLT.Product | Unrestricted | None | Product analysis |
| SalesLT.ProductCategory | Unrestricted | None | Category trends |
| SalesLT.ProductDescription | Unrestricted | None | Content analysis |
| SalesLT.ProductModel | Unrestricted | None | Model performance |
| SalesLT.ProductModelProductDescription | Unrestricted | None | Language availability |
| SalesLT.SalesOrderHeader | Filtered | None (but CustomerID column excluded) | 14 columns: SalesOrderID, OrderDate, DueDate, ShipDate, Status, OnlineOrderFlag, SalesOrderNumber, ShipMethod, SubTotal, TaxAmt, Freight, TotalDue | ✓ Excludes: CustomerID (PII), BillToAddressID, ShipToAddressID, CreditCardApprovalCode |
| SalesLT.SalesOrderDetail | Unrestricted | None | Unit economics data |

**Denied Tables (4):**
- SalesLT.Customer (PII - no individual customer linking)
- SalesLT.Address (PII)
- SalesLT.CustomerAddress (PII)

**Total Columns:** 54 readable columns

**Key Security Principles:**
- ✓ Revenue analysis without exposing customer identities (no CustomerID)
- ✓ Profitability and margin analysis via order details
- ✓ Aggregation-friendly: Orders can be grouped by date, status, method
- ✓ No access to PII (customer names, emails, addresses)
- ✓ No access to payment credentials

---

### 5. SUPPORT ROLE
**Purpose:** Support staff - limited lookup + status only, no financial data

**Tables Accessible (3 / 10):**

| Table | Access Type | Filter Columns | Read Columns | Security Notes |
|-------|------------|----------------|--------------|-----------------|
| SalesLT.Customer | Filtered | CustomerID (id) | 6: FirstName, LastName, CompanyName, EmailAddress, Phone | ✓ Excludes: Title, MiddleName, Suffix, SalesPerson, PasswordHash, PasswordSalt |
| SalesLT.SalesOrderHeader | Filtered | None (full) | 7: SalesOrderID, OrderDate, ShipDate, Status, SalesOrderNumber, OnlineOrderFlag, ShipMethod | ✓ Excludes: All financial (SubTotal, TaxAmt, Freight, TotalDue), CustomerID, CreditCardApprovalCode, Address IDs |
| SalesLT.Address | Unrestricted | None | All | Shipping address validation |

**Denied Tables (7):**
- SalesLT.SalesOrderDetail (pricing/discount details)
- SalesLT.Product (internal)
- SalesLT.ProductCategory (internal)
- SalesLT.ProductDescription (internal)
- SalesLT.ProductModel (internal)
- SalesLT.ProductModelProductDescription (internal)
- SalesLT.CustomerAddress (use Address directly)

**Total Columns:** 16 readable columns

**Key Security Principles:**
- ✓ Customer lookup by ID or name (for support inquiries)
- ✓ Order status tracking (can tell customer "Your order is Shipped")
- ✓ Shipping method visibility (customer asks "how will it arrive?")
- ✓ NO access to order total/pricing (support cannot discuss prices, only sales can)
- ✓ NO access to addresses except generic Address table (not customer-linked)
- ✓ NO access to authentication secrets (PasswordHash, PasswordSalt)

---

## SECURITY METRICS

### Column Coverage by Sensitivity Level

**Tier 1 (Public - visible to all roles accessing table):**
- Dates: OrderDate, DueDate, ShipDate, ModifiedDate
- Identifiers: ProductID, CategoryID, ModelID, SalesOrderNumber
- Names: FirstName, LastName, CompanyName, ProductName, CategoryName

**Tier 2 (Business - visible to sales/admin, some analysts):**
- Pricing: ListPrice, StandardCost, UnitPrice, UnitPriceDiscount, LineTotal, SubTotal, TaxAmt, Freight, TotalDue
- Status: Status, OnlineOrderFlag, RevisionNumber
- Addresses: AddressLine1, City, StateProvince, CountryRegion, PostalCode

**Tier 3 (Sensitive - admin only):**
- Payment: CreditCardApprovalCode
- Authentication: PasswordHash, PasswordSalt
- System: rowguid (replication GUID)

### Denied Column Patterns

| Pattern | Reason | Affected Roles |
|---------|--------|-----------------|
| PasswordHash, PasswordSalt | Authentication secrets - no role should access except via bcrypt/hash verification | customer, sales, analyst, support |
| CreditCardApprovalCode | Payment credentials - never query directly | customer, analyst, support |
| rowguid | System metadata for replication, not business data | customer, analyst, support |
| ModifiedDate | Timestamp audit trail, restricted to admin/compliance | customer, support |
| SalesPerson (in Customer) | Admin/internal tracking | customer, support |
| BillToAddressID, ShipToAddressID (in SalesOrderHeader) | FK linking, not direct access | analyst, support |

---

## FILTER TYPES USED

### Filter: "id"
Applied to primary/foreign key columns where value depends on session/login context.
**Examples:** CustomerID, SalesOrderID, AddressID
**Enforcement:** WHERE column = @runtime_value (passed from session)
**Roles Using:** customer, support

### Filter: "enum"
Applied to status/type columns with fixed set of allowed values.
**Examples:** Status (1-6), AddressType (Billing, Shipping, Main Office, etc.)
**Enforcement:** WHERE column IN (allowed_values)
**Roles Using:** customer (Status 1-6)

### Filter: "none"
Applied to readable columns with no filter restriction (but column must exist in permission rule).
**Examples:** FirstName, LastName, ProductName, OrderDate
**Enforcement:** Column is accessible with no WHERE clause on it
**Roles Using:** All roles with column-level permissions

---

## IMPLEMENTATION CHECKLIST

### For SQL Query Generator / LLM Agent
- [ ] Load PERMISSIONS dictionary at startup
- [ ] On each query, load RUNTIME_VALUES for logged-in user
- [ ] Call build_permission_block(user) and inject into LLM system prompt
- [ ] Validate generated SQL against permitted tables and filters
- [ ] Reject queries trying to access denied tables or columns
- [ ] For "id" filters: inject WHERE clause even if user doesn't explicitly mention it
- [ ] For "enum" filters: enforce IN clause with preset values
- [ ] Return structured error JSON if permissions violated

### For Audit/Compliance
- [ ] Log all queries by role + username
- [ ] Alert on denied table/column access attempts
- [ ] Periodically review which roles access which columns
- [ ] Test that filters are actually applied (penetration test)

---

## TESTING EXAMPLES

### Test Case 1: Customer Self-Service
**User:** john_doe (customer)
**Query:** "Show me my orders"
**Expected:** 
- Generated SQL filters by CustomerID = 29531
- Only SalesOrderHeader + SalesOrderDetail rows for that customer
- Status, ShipDate, OrderDate visible
- SubTotal, TotalDue NOT visible ✗

### Test Case 2: Sales Order Management
**User:** alice@sales (sales)
**Query:** "Show all orders from Q2 2008"
**Expected:**
- All rows, all customers
- Full pricing visible
- Can see CreditCardApprovalCode if needed ✓

### Test Case 3: Analyst Revenue Report
**User:** bob@analytics (analyst)
**Query:** "Total revenue by status"
**Expected:**
- GROUP BY Status
- SUM(TotalDue), SUM(SubTotal), etc.
- NO customer names, emails, addresses
- Cannot see which customer placed order ✗

### Test Case 4: Support Shipping Lookup
**User:** carol@support (support)
**Query:** "What's the status of order 71774?"
**Expected:**
- Can retrieve Status, ShipDate, ShipMethod
- Cannot see order total (SubTotal) ✗
- Cannot see customer name from SalesOrderHeader ✗
- Can see shipping address if needed

---

## DEPLOYMENT NOTES

1. **permissions.py** - Use in Python agent for dynamic rule enforcement
2. **permissions.json** - Use for API/frontend policy distribution
3. **build_permission_block()** - Call to generate system prompt for LLM
4. **RUNTIME_VALUES** - Populate from session/authentication system on login
5. **Audit** - Log all queries using PERMISSIONS + actual SQL executed

---

## References

- **Filter Rule Types:** id, enum, none, (empty = full access)
- **Total Managed Tables:** 10 SalesLT tables
- **Total Managed Columns:** 100+
- **Roles Defined:** 5
- **Enforcement Points:** Query validator, LLM system prompt, SQL interceptor
