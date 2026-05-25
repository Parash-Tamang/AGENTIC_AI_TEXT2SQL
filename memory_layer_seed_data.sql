-- ============================================================
-- Memory Layer Seed Data — AdventureWorksLT2019
-- 5 realistic turns per table, derived from actual schema
-- ============================================================

-- ────────────────────────────────────────────────────────────
-- 1. GLOBAL MEMORY
--    Cross-db learnings: SQL fix patterns, hallucination blocks
-- ────────────────────────────────────────────────────────────

INSERT INTO memory_global (memory_type, key_pattern, correction, confidence, hit_count, created_at, updated_at) VALUES

-- Turn 1: LLM tried to GROUP BY without including all SELECT columns
('sql_fix',
 'SELECT with non-aggregated columns missing from GROUP BY',
 'Always include every non-aggregated SELECT column in GROUP BY. '
 + 'Example: SELECT c.CustomerID, c.FirstName, COUNT(o.SalesOrderID) ... '
 + 'GROUP BY c.CustomerID, c.FirstName',
 0.90, 7,
 '2024-11-01 09:12:00', '2025-01-15 14:22:00'),

-- Turn 2: LLM hallucinated a table that does not exist
('hallucination_block',
 'SalesLT.SalesOrderLine',
 'Table does not exist. Use SalesLT.SalesOrderDetail for line-level order data. '
 + 'Key columns: SalesOrderID (FK→SalesOrderHeader), ProductID (FK→Product), OrderQty, UnitPrice, LineTotal.',
 0.95, 12,
 '2024-11-03 11:05:00', '2025-02-01 08:44:00'),

-- Turn 3: LLM used ISNULL incorrectly across joined nullables
('sql_fix',
 'ISNULL used on non-nullable join key causing incorrect results',
 'Do not wrap join keys in ISNULL. SalesOrderDetail.SalesOrderID and '
 + 'SalesOrderHeader.SalesOrderID are both NOT NULL — ISNULL adds unnecessary '
 + 'overhead and can mask type mismatches. Join directly on the integer keys.',
 0.75, 4,
 '2024-11-10 15:33:00', '2024-12-20 10:10:00'),

-- Turn 4: LLM computed revenue using ListPrice instead of UnitPrice
('sql_fix',
 'Revenue calculation using Product.ListPrice instead of SalesOrderDetail.UnitPrice',
 'Use SalesOrderDetail.UnitPrice * (1 - UnitPriceDiscount) * OrderQty for actual '
 + 'revenue per line. Product.ListPrice is the catalogue price, not what was charged. '
 + 'SalesOrderDetail.LineTotal = UnitPrice * (1 - UnitPriceDiscount) * OrderQty is precomputed.',
 0.88, 6,
 '2024-11-18 09:00:00', '2025-01-28 16:55:00'),

-- Turn 5: LLM returned duplicate rows by missing DISTINCT on cross-reference join
('sql_fix',
 'Duplicate customer rows when joining Customer → CustomerAddress → Address without filtering AddressType',
 'CustomerAddress is a cross-reference with multiple address types per customer '
 + '(Main Office, Shipping, Billing). Add WHERE ca.AddressType = ''Main Office'' '
 + 'or use ROW_NUMBER() PARTITION BY CustomerID ORDER BY AddressType to get one row per customer.',
 0.85, 9,
 '2024-12-01 10:15:00', '2025-02-10 09:30:00');


-- ────────────────────────────────────────────────────────────
-- 2. DOMAIN MEMORY
--    Per db_type + schema: join paths, quirks, seed table hints
-- ────────────────────────────────────────────────────────────

INSERT INTO memory_domain (db_type, schema_name, memory_type, key_pattern, payload, confidence, hit_count, created_at, updated_at) VALUES

-- Turn 1: BFS discovered canonical join path for order→product queries
('sqlserver', 'SalesLT', 'join_path',
 'SalesOrderHeader → SalesOrderDetail → Product',
 '{"path": ["SalesLT.SalesOrderHeader", "SalesLT.SalesOrderDetail", "SalesLT.Product"], '
 + '"joins": ['
 + '  {"from": "SalesOrderHeader.SalesOrderID", "to": "SalesOrderDetail.SalesOrderID", "type": "INNER"},'
 + '  {"from": "SalesOrderDetail.ProductID",    "to": "Product.ProductID",              "type": "INNER"}'
 + '], "bfs_hops": 2}',
 0.95, 14,
 '2024-11-01 09:15:00', '2025-02-12 11:00:00'),

-- Turn 2: Hierarchical self-join quirk in ProductCategory
('sqlserver', 'SalesLT', 'quirk',
 'ProductCategory has self-referencing ParentProductCategoryID — naive join duplicates rows',
 '{"note": "ProductCategory.ParentProductCategoryID FK references ProductCategory.ProductCategoryID. '
 + 'Top-level categories have NULL ParentProductCategoryID (Bikes, Components, Clothing, Accessories). '
 + 'Always alias: parent AS pc_parent, child AS pc_child. '
 + 'Use LEFT JOIN to retain top-level categories in result sets.", '
 + '"example": "SELECT pc_child.Name AS SubCategory, pc_parent.Name AS ParentCategory '
 + 'FROM SalesLT.ProductCategory pc_child '
 + 'LEFT JOIN SalesLT.ProductCategory pc_parent ON pc_child.ParentProductCategoryID = pc_parent.ProductCategoryID"}',
 0.90, 8,
 '2024-11-05 14:20:00', '2025-01-30 13:45:00'),

-- Turn 3: Multi-language quirk in ProductModelProductDescription
('sqlserver', 'SalesLT', 'quirk',
 'ProductModelProductDescription.Culture is NCHAR(6) padded with spaces — LIKE or RTRIM needed',
 '{"note": "Culture values are stored as fixed 6-char NCHAR, e.g. ''en    '' not ''en''. '
 + 'Always filter with: WHERE RTRIM(pmdc.Culture) = ''en'' ",'
 + '"affected_query_patterns": ["product descriptions", "multilingual", "language filter"], '
 + '"tables": ["SalesLT.ProductModelProductDescription"]}',
 0.92, 11,
 '2024-11-12 10:05:00', '2025-02-05 08:20:00'),

-- Turn 4: Seed table hint — SalesOrderHeader is the entry point for all order queries
('sqlserver', 'SalesLT', 'seed_table_hint',
 'order|revenue|sales|purchase|invoice',
 '{"seed_tables": ["SalesLT.SalesOrderHeader"], '
 + '"note": "SalesOrderHeader is the fact table for all order-level queries. '
 + 'TotalDue = SubTotal + TaxAmt + Freight. Status 5 = Shipped. '
 + 'OnlineOrderFlag BIT: 0=salesperson, 1=online.", '
 + '"common_downstream": ["SalesLT.SalesOrderDetail", "SalesLT.Customer", "SalesLT.Address"]}',
 0.93, 17,
 '2024-11-01 08:00:00', '2025-02-14 10:30:00'),

-- Turn 5: SalesOrderHeader→Address has two FKs (ship and bill) — LLM kept joining both accidentally
('sqlserver', 'SalesLT', 'quirk',
 'SalesOrderHeader has two FK columns to Address: ShipToAddressID and BillToAddressID',
 '{"note": "Joining SalesOrderHeader to Address without aliasing produces a cross-join effect. '
 + 'Always specify intent: ship address or billing address. ",'
 + '"correct_pattern": '
 + '"JOIN SalesLT.Address ship_addr ON soh.ShipToAddressID = ship_addr.AddressID '
 + ' JOIN SalesLT.Address bill_addr ON soh.BillToAddressID = bill_addr.AddressID", '
 + '"tables": ["SalesLT.SalesOrderHeader", "SalesLT.Address"]}',
 0.88, 6,
 '2024-12-03 09:45:00', '2025-01-22 14:10:00');


-- ────────────────────────────────────────────────────────────
-- 3. USER PREFERENCES
--    Inferred silently from session behavior
-- ────────────────────────────────────────────────────────────

INSERT INTO memory_user_prefs (session_id, user_id, pref_key, pref_value, inferred, confidence, updated_at) VALUES

-- Turn 1: User consistently asks for revenue in aggregated table form
('sess_u001_aw', 'user_001',
 'output_format', 'table',
 1, 0.88,
 '2024-11-01 10:00:00'),

-- Turn 2: User always filters to shipped orders (Status = 5)
('sess_u001_aw', 'user_001',
 'default_order_status_filter', '5',
 1, 0.82,
 '2024-11-05 11:30:00'),

-- Turn 3: User prefers full customer name concatenated, not split first/last
('sess_u001_aw', 'user_001',
 'customer_name_format',
 'CONCAT(c.FirstName, '' '', ISNULL(c.MiddleName + '' '', ''''), c.LastName)',
 1, 0.79,
 '2024-11-12 09:15:00'),

-- Turn 4: User's date range default is current calendar year
('sess_u001_aw', 'user_001',
 'date_range_default',
 'YEAR(OrderDate) = YEAR(GETDATE())',
 1, 0.75,
 '2024-11-20 14:45:00'),

-- Turn 5: User prefers product category rolled up to parent (top-level only)
('sess_u001_aw', 'user_001',
 'product_category_level',
 'parent_only',
 1, 0.71,
 '2024-12-01 16:00:00');


-- ────────────────────────────────────────────────────────────
-- 4. CUSTOM PROMPTS
--    System-level and domain-level instruction overrides
-- ────────────────────────────────────────────────────────────

INSERT INTO memory_custom_prompts (scope, scope_key, prompt_role, content, active, updated_at) VALUES

-- Turn 1: Global system note — always qualify schema
('global', NULL, 'system',
 'Always fully qualify table names with schema prefix in SQL Server queries. '
 + 'Use SalesLT.Customer, not just Customer. The database contains both dbo and SalesLT schemas.',
 1, '2024-11-01 08:00:00'),

-- Turn 2: Domain note — money columns are MONEY type, cast for display
('domain', 'sqlserver::SalesLT', 'domain_note',
 'MONEY columns (UnitPrice, ListPrice, StandardCost, SubTotal, TaxAmt, Freight, TotalDue, LineTotal) '
 + 'should be cast to DECIMAL(18,2) in SELECT for clean display: CAST(col AS DECIMAL(18,2)). '
 + 'Never SUM a MONEY column directly into another MONEY — intermediate overflow risk on large datasets.',
 1, '2024-11-05 09:00:00'),

-- Turn 3: SQL generation hint — avoid SELECT * on Product due to VARBINARY thumbnail column
('domain', 'sqlserver::SalesLT', 'sql_hint',
 'Never use SELECT * on SalesLT.Product. The ThumbNailPhoto column is VARBINARY and returns '
 + 'large binary blobs that bloat result sets and token counts. '
 + 'Always select named columns explicitly; exclude ThumbNailPhoto unless the user explicitly asks for images.',
 1, '2024-11-10 10:30:00'),

-- Turn 4: User-level prompt — this user works in sales reporting context
('user', 'user_001', 'system',
 'This user works in sales analytics. Prefer queries that aggregate by month or quarter. '
 + 'When the user asks about "customers" they typically mean paying customers with at least one shipped order '
 + '(SalesOrderHeader.Status = 5), not all rows in SalesLT.Customer.',
 1, '2024-11-20 14:00:00'),

-- Turn 5: Global SQL hint — rowguid columns should be excluded from SELECT unless asked
('global', NULL, 'sql_hint',
 'Exclude rowguid (UNIQUEIDENTIFIER) columns from SELECT unless the user explicitly requests them. '
 + 'They are replication artifacts and add no analytical value. '
 + 'This applies to: Customer.rowguid, Address.rowguid, Product.rowguid, '
 + 'CustomerAddress.rowguid, SalesOrderHeader.rowguid, SalesOrderDetail.rowguid.',
 1, '2024-12-01 09:00:00');


-- ────────────────────────────────────────────────────────────
-- 5. CONVERSATION HISTORY
--    5 turns of a real analytics session on AdventureWorksLT2019
-- ────────────────────────────────────────────────────────────

INSERT INTO memory_history
  (session_id, turn_number, user_query, refined_query, generated_sql,
   execution_ok, self_rag_retry, retry_issues, retry_hint,
   user_response, domain_context, db_type, created_at)
VALUES

-- Turn 1: Simple customer count — succeeded first try
('sess_u001_aw', 1,
 'how many customers do we have',
 'Total count of distinct customers in the Customer table',
 'SELECT COUNT(CustomerID) AS TotalCustomers FROM SalesLT.Customer;',
 1, 0, NULL, NULL,
 'There are 847 customers in the system.',
 'sales_analytics', 'sqlserver',
 '2024-12-10 09:05:00'),

-- Turn 2: Revenue by category — LLM used ListPrice, caught by results validator, retried
('sess_u001_aw', 2,
 'show me revenue by product category this year',
 'Total revenue grouped by top-level product category for the current calendar year',
 'SELECT pc_parent.Name AS Category,
    CAST(SUM(sod.LineTotal) AS DECIMAL(18,2)) AS TotalRevenue
 FROM SalesLT.SalesOrderHeader soh
 INNER JOIN SalesLT.SalesOrderDetail sod ON soh.SalesOrderID = sod.SalesOrderID
 INNER JOIN SalesLT.Product p            ON sod.ProductID    = p.ProductID
 INNER JOIN SalesLT.ProductCategory pc   ON p.ProductCategoryID = pc.ProductCategoryID
 LEFT  JOIN SalesLT.ProductCategory pc_parent
            ON pc.ParentProductCategoryID = pc_parent.ProductCategoryID
 WHERE YEAR(soh.OrderDate) = YEAR(GETDATE())
   AND soh.Status = 5
 GROUP BY pc_parent.Name
 ORDER BY TotalRevenue DESC;',
 1, 0, NULL, NULL,
 'Revenue by category this year: Bikes $2.4M, Components $890K, Clothing $210K, Accessories $145K.',
 'sales_analytics', 'sqlserver',
 '2024-12-10 09:08:00'),

-- Turn 3: Top customers — retry triggered because LLM joined both address FKs without aliasing
('sess_u001_aw', 3,
 'who are the top 10 customers by total spend with their city',
 'Top 10 customers ranked by total order value (TotalDue), including their main office city',
 'SELECT TOP 10
    CONCAT(c.FirstName, '' '', ISNULL(c.MiddleName + '' '', ''''), c.LastName) AS CustomerName,
    c.CompanyName,
    a.City,
    a.StateProvince,
    CAST(SUM(soh.TotalDue) AS DECIMAL(18,2)) AS TotalSpend
 FROM SalesLT.SalesOrderHeader soh
 INNER JOIN SalesLT.Customer        c   ON soh.CustomerID         = c.CustomerID
 INNER JOIN SalesLT.CustomerAddress ca  ON c.CustomerID           = ca.CustomerID
 INNER JOIN SalesLT.Address         a   ON ca.AddressID           = a.AddressID
 WHERE ca.AddressType = ''Main Office''
   AND soh.Status = 5
 GROUP BY c.CustomerID, c.FirstName, c.MiddleName, c.LastName, c.CompanyName, a.City, a.StateProvince
 ORDER BY TotalSpend DESC;',
 1, 1,
 '["duplicate_rows","join_explosion"]',
 'SalesOrderHeader has two FK columns to Address (ShipToAddressID, BillToAddressID). '
 + 'Join Customer→CustomerAddress→Address instead for customer city. Filter AddressType = Main Office.',
 'Top 10 customers by spend retrieved. Jon Yang of Progressive Sports leads at $124,860.',
 'sales_analytics', 'sqlserver',
 '2024-12-10 09:14:00'),

-- Turn 4: Product description lookup — LLM forgot Culture padding quirk, retried
('sess_u001_aw', 4,
 'give me English descriptions for all mountain bikes',
 'English product descriptions for products in the Mountain Bikes sub-category',
 'SELECT p.Name AS ProductName,
    pc.Name  AS SubCategory,
    pd.Description
 FROM SalesLT.Product                        p
 INNER JOIN SalesLT.ProductCategory          pc    ON p.ProductCategoryID    = pc.ProductCategoryID
 INNER JOIN SalesLT.ProductModel             pm    ON p.ProductModelID       = pm.ProductModelID
 INNER JOIN SalesLT.ProductModelProductDescription pmdc
                                                   ON pm.ProductModelID      = pmdc.ProductModelID
 INNER JOIN SalesLT.ProductDescription       pd    ON pmdc.ProductDescriptionID = pd.ProductDescriptionID
 WHERE pc.Name = ''Mountain Bikes''
   AND RTRIM(pmdc.Culture) = ''en''
 ORDER BY p.Name;',
 1, 1,
 '["empty_result"]',
 'ProductModelProductDescription.Culture is NCHAR(6) padded with spaces. '
 + 'Use RTRIM(pmdc.Culture) = ''en'' not direct equality on ''en''.',
 'Found 32 mountain bike products with English descriptions.',
 'sales_analytics', 'sqlserver',
 '2024-12-10 09:21:00'),

-- Turn 5: Month-over-month order trend — succeeded first try, prefs applied automatically
('sess_u001_aw', 5,
 'show me monthly order trend for the past 6 months',
 'Monthly order count and total revenue for the last 6 calendar months, shipped orders only',
 'SELECT
    FORMAT(soh.OrderDate, ''yyyy-MM'')          AS OrderMonth,
    COUNT(DISTINCT soh.SalesOrderID)            AS OrderCount,
    CAST(SUM(soh.TotalDue) AS DECIMAL(18,2))   AS TotalRevenue
 FROM SalesLT.SalesOrderHeader soh
 WHERE soh.Status = 5
   AND soh.OrderDate >= DATEADD(MONTH, -6, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1))
 GROUP BY FORMAT(soh.OrderDate, ''yyyy-MM'')
 ORDER BY OrderMonth;',
 1, 0, NULL, NULL,
 'Monthly trend retrieved for 6 months. Peak was September with 48 orders and $1.2M revenue.',
 'sales_analytics', 'sqlserver',
 '2024-12-10 09:28:00');

-- ============================================================
-- END OF SEED DATA
-- ============================================================
