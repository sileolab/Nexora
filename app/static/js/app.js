/**
 * Nexora Studio - Frontend Application Script
 * Vanilla JavaScript implementation with async API integration, state management,
 * polling, real-time filtering, URL parsing, and file export.
 */

'use strict';

// ============================================================================
// 1. State Management
// ============================================================================
const state = {
    currentLang: 'en',
    activeTab: 'discover',
    discoveryJobId: null,
    extractionJobId: null,
    discoveredPages: [],
    selectedUrls: new Set(),
    extractionUrls: new Set(),
    extractedDocuments: [],
    isDiscovering: false,
    isExtracting: false,
    pollInterval: null,
    activePollingType: null, // 'discovery' | 'extraction'
    searchQuery: ''
};


// ============================================================================
// 1.1. Internationalization (I18N) Dictionary & Helper Engine
// ============================================================================
const I18N_EN = {
    "app_title": "Nexora Studio | Intelligent Web Discovery, Extraction & RAG Pipeline",
    "nav_main_tabs": "Main platform navigation tabs",
    "nav_discover": "URL Discovery",
    "nav_discover_title": "Crawl and discover website structure",
    "nav_extract": "Content Extraction",
    "nav_extract_title": "Structured content extraction and cleaning",
    "nav_ai": "RAG Studio",
    "nav_ai_title": "AI Studio: LLM · Text Chunking · Vector Embedding",
    "nav_files": "File Processing",
    "nav_eval": "Retrieval Evaluation",
    "nav_eval_title": "Retrieval Evaluation: Benchmark Metrics, Compare Methods & Diagnostics",
    "nav_files_title": "File & Data Processing: Normalize, Transform & Chunk documents",
    "sys_ready": "System Ready",
    "sys_status_title": "Server status and API responsiveness",
    "disc_title": "URL Discovery & Website Crawler",
    "disc_subtitle": "Smart page discovery respecting Robots.txt and extracting Sitemaps",
    "disc_adv_btn_title": "Configure depth, concurrency, timeouts and regex filters",
    "disc_adv_settings": "Advanced Settings",
    "disc_url_placeholder": "Enter root website URL (e.g., https://example.com)...",
    "disc_start_title": "Click or press Enter to start discovery",
    "disc_start_btn": "Start Discovery",
    "disc_stop_title": "Immediately abort discovery process",
    "disc_stop_btn": "Stop",
    "disc_max_depth": "Max Depth",
    "disc_max_pages": "Max Pages",
    "disc_timeout": "Timeout (Seconds)",
    "disc_concurrency": "Concurrency",
    "disc_delay": "Delay (Seconds)",
    "disc_prefix": "Path Prefix",
    "disc_prefix_placeholder": "/blog/ or /articles/",
    "disc_subdomains": "Allow Subdomains",
    "disc_query_params": "Keep Query Parameters",
    "disc_sitemap": "Use Sitemap (sitemap.xml)",
    "disc_include_patterns": "Include Patterns (Regex - one per line):",
    "disc_exclude_patterns": "Exclude Patterns (Regex - one per line):",
    "metric_job_id": "Job ID:",
    "status_ready_start": "Ready to Start",
    "disc_stat_total": "Total Pages",
    "disc_stat_crawled": "Crawled",
    "disc_stat_failed": "Failed",
    "disc_stat_selected": "Selected",
    "search_disc_placeholder": "Search URLs or page title...",
    "disc_select_all_title": "Select all filtered pages",
    "btn_select_all": "Select All",
    "disc_deselect_all_title": "Deselect all pages",
    "btn_deselect_all": "Deselect All",
    "disc_send_ext_title": "Transfer selected URLs to Extraction queue",
    "btn_send_extraction_prefix": "Send to Extraction",
    "disc_export_txt_title": "Export discovered URLs as a plain TXT file",
    "btn_export_urls": "Export URLs",
    "th_url": "URL",
    "th_title": "Page Title",
    "th_status": "Status",
    "th_source": "Source",
    "th_depth": "Depth",
    "empty_disc_title": "No pages discovered yet",
    "empty_disc_desc": "Enter a root website URL above and click 'Start Discovery'.",
    "footer_showing": "Showing",
    "footer_of": "of",
    "footer_disc_pages": "discovered pages",
    "ext_title": "Structured Extraction & Content Settings",
    "ext_subtitle": "Boilerplate removal, article text extraction, and clean Markdown conversion",
    "ext_queue_title": "Extraction URL Queue:",
    "ext_queue_placeholder": "Enter target URLs manually (one per line)...",
    "ext_add_btn_title": "Add entered URLs to extraction queue",
    "ext_btn_add": "Add to Queue",
    "ext_clear_btn_title": "Clear entire extraction queue",
    "ext_btn_clear": "Clear Queue",
    "ext_empty_notice": "No URLs in queue. Send from Discovery tab or add manually above.",
    "ext_engine_label": "Extraction Engine",
    "ext_eng_auto": " Smart Auto (Auto Mode — Page detection & Fallback)",
    "ext_eng_playwright": " Playwright Chromium (Advanced SPA & JS-heavy rendering)",
    "ext_eng_crawl4ai": " Crawl4AI (Headless browser rendering for JS/SPA)",
    "ext_eng_trafilatura": " Trafilatura (Articles, blogs & structured text)",
    "ext_eng_bs4": " BeautifulSoup (DOM control, tables & microdata)",
    "ext_eng_compare": " Full Comparison (Compare Mode — Multi-engine benchmark)",
    "ext_crawl_mode": "Crawl Mode",
    "ext_crawl_mode_title": "Traversal and route capture mode",
    "ext_mode_single": "Single Page",
    "ext_mode_site": "Site Crawl",
    "ext_mode_spa": "Capture SPA & Routes",
    "ext_mode_compare": "Compare 3 Engines",
    "ext_render_mode": "Browser Render",
    "ext_render_mode_title": "Playwright browser rendering strategy",
    "ext_render_auto": "Auto Detect",
    "ext_render_never": "Fast HTTP Only",
    "ext_render_always": "Always Headless",
    "ext_quality_threshold": "Quality Threshold",
    "ext_quality_threshold_title": "Minimum quality score before fallback (0 to 100)",
    "ext_category_label": "Category Tag",
    "ext_category_title": "Topic categorization tag attached to documents",
    "ext_category_placeholder": "e.g., articles, news, tech...",
    "ext_concurrency_label": "Concurrency",
    "ext_concurrency_title": "Number of concurrent extraction requests",
    "ext_delay_label": "Initial Loading Delay (s)",
    "ext_delay_placeholder": "0 (Smart auto-detection)",
    "ext_wait_label": "Wait Selector (CSS)",
    "ext_wait_selector_title": "Optional CSS selector to wait for main content element (e.g. #main, .article-content)",
    "ext_wait_placeholder": "e.g., #main, .article-content",
    "ext_visible_only": "<strong>Extract Visually Rendered Content Only</strong> (What is visible after page load)",
    "ext_visible_only_title": "Extract strictly what is rendered on screen (eliminates hidden tabs, collapsed menus, and background SPA views)",
    "ext_start_btn": "Start Content Extraction",
    "ext_start_btn_title": "Begin structured content extraction for all queued URLs",
    "ext_stop_btn": "Stop Extraction",
    "ext_retry_btn": "Retry Failed Items",
    "ext_banner_title": "AI Studio & RAG Pipeline",
    "ext_banner_desc": "Once extraction finishes, enrich documents with LLMs, generate semantic chunks, and build 1536-dimensional embeddings.",
    "ext_banner_btn": "Open RAG Studio",
    "ext_stat_total": "Total Documents",
    "ext_stat_success": "Extracted",
    "ext_stat_failed": "Failed",
    "ext_stat_words": "Words",
    "ext_results_title": "Extracted Documents",
    "ext_dedup_label": "Remove Duplicates",
    "ext_dedup_title": "Remove duplicate pages and documents before downloading export files",
    "ext_export_hint": "Export:",
    "ext_btn_transfer_ai": "Transfer to RAG Studio",
    "ext_btn_transfer_ai_title": "Send extracted documents to the AI and RAG pipeline",
    "th_doc_url": "Page URL",
    "th_doc_title": "Document Title",
    "th_engine": "Engine / Type",
    "th_words": "Words",
    "th_quality": "Quality Score",
    "th_preview": "Preview",
    "empty_ext_title": "No pages extracted yet",
    "empty_ext_desc": "Add target URLs above and click 'Start Content Extraction'.",
    "ext_footer_count": "Total Documents:",
    "footer_items": "items",
    "footer_docs": "documents",
    "ai_title": "AI & Retrieval-Augmented Generation (RAG) Studio",
    "ai_subtitle": "Semantic chunking, vector embedding, and verified structuring for vector databases",
    "ai_active_job": "Active Job:",
    "ai_status_checking": "Checking connection to AI provider...",
    "ai_status_ready": "AI provider connected. All LLM and Embedding models are active.",
    "ai_status_no_key": "<code>NEXORA_OPENAI_API_KEY</code> is not configured in <code>.env</code>. <strong>Text Chunking is fully operational offline</strong>.",
    "ai_cfg_llm": "LLM Model:",
    "ai_cfg_embed": "Embedding Model:",
    "ai_pipe_step1": "1. LLM Structuring + Fact-Check",
    "ai_pipe_step2": "2. Text Chunking",
    "ai_pipe_step3": "3. Vector Embedding",
    "ai_btn_run_title": "Execute all selected pipeline stages sequentially",
    "ai_btn_run_pipeline": "Run Unified Pipeline",
    "ai_step1_name": "1. LLM Structuring",
    "ai_step2_name": "2. Text Chunking",
    "ai_step3_name": "3. Vector Embedding",
    "ai_stat_enhanced": "RAG Enhanced Docs:",
    "ai_stat_chunks": "Produced Chunks:",
    "ai_stat_vectors": "Generated Vectors:",
    "ai_card1_title": "Precise RAG Structuring with LLM",
    "ai_model_lbl": "Model:",
    "ai_grounding_title": "Automated Grounding & Fact-Checking",
    "ai_grounding_desc": "Every answer includes verified textual evidence; numbers, dates, and names are strictly cross-referenced against the source document.",
    "ai_card1_feat1": "Analytical 2-3 sentence summary without hallucination",
    "ai_card1_feat2": "Extract 5 to 10 precise topical keywords",
    "ai_card1_feat3": "Generate Q&A pairs with verified citation evidence",
    "ai_card1_btn": "Run LLM Structuring & Verification",
    "ai_export_structured": "Export Structured Data:",
    "ai_card2_title": "Text Chunking",
    "ai_card2_subtitle": "Convert into standardized knowledge chunks",
    "ai_badge_offline": "100% Offline & Free",
    "ai_card2_desc": "Smart document chunking preserving H1-H6 heading hierarchy, avoiding word cutting, with seamless overlap.",
    "ai_chunk_strat_label": "Chunking Strategy:",
    "ai_chunk_auto": "Smart Auto — Based on page structure and type (Recommended)",
    "ai_chunk_heading": "Semantic Heading — H1 to H6 heading hierarchy",
    "ai_chunk_paragraph": "Natural Paragraph — Paragraph boundaries with sub-chunking",
    "ai_chunk_sentence": "Sentence — Sentence boundaries preserving decimals & links",
    "ai_chunk_fixed": "Fixed Size — Character window preserving word boundaries",
    "ai_chunk_size_lbl": "Chunk Size (chars):",
    "ai_chunk_overlap_lbl": "Overlap (chars):",
    "ai_chunk_dedup_lbl": "<strong>Deduplicate Chunks</strong>",
    "ai_card2_btn": "Run Text Chunking",
    "ai_export_chunks": "Export Chunk Files:",
    "ai_card3_title": "Vector Embedding",
    "ai_card3_desc": "Batch generation of 1536-dimensional dense vectors with automatic retries, ready for vector databases.",
    "ai_card3_btn": "Generate Vector Embeddings",
    "ai_export_vectors": "Vector Database Export:",
    "ai_export_vectors_title": "Download JSONL file containing text, metadata, and 1536-dimensional vector arrays",
    "ai_btn_download_vectors": "Download Chunks + Vectors (JSONL)",
    "ai_prev_title": "Live RAG Pipeline Output Preview",
    "ai_prev_subtitle": "Inspect JSON structures, grounded Q&A pairs, and chunks online",
    "status_ready": "Ready",
    "ai_prev_tab_json": "RAG JSON + Grounding",
    "ai_prev_tab_chunks": "Chunks",
    "fp_title": "File & RAG Data Processing",
    "fp_subtitle": "Upload Markdown, Text, JSON, JSONL, CSV; Persian normalization, transformations, and chunking",
    "fp_drop_title": "Drag and drop your file here, or click to browse",
    "fp_drop_hint": "Supports Markdown (.md), Plain Text (.txt), JSON (.json), JSONL (.jsonl), and CSV (.csv) — up to 10MB",
    "fp_info_filename": "File Name:",
    "fp_info_format": "Format:",
    "fp_info_size": "File Size:",
    "fp_info_lines": "Lines / Records:",
    "fp_info_encoding": "Encoding:",
    "fp_ops_title": "Pipeline Operations & Configuration",
    "fp_ops_subtitle": "Select processing pipeline operations and configure output parameters",
    "fp_ops_select_lbl": "Select Pipeline Operations:",
    "fp_op_norm_title": "Persian Normalization & Text Cleanup",
    "fp_op_norm_desc": "Unicode NFC, character/digit unification, ZWNJ normalization for verbs and suffixes",
    "fp_op_chunk_title": "Smart Chunking",
    "fp_op_chunk_desc": "Convert document into semantic chunks preserving H1-H6 context, paragraphs, and words",
    "fp_op_ai_title": "AI Optimization (RAG Enhancer)",
    "fp_op_ai_desc": "Automated summary, topic tags, keywords, and grounded Q&A pairs with source citations",
    "fp_op_embed_title": "Vector Embeddings",
    "fp_op_embed_desc": "Generate 1536-dim dense vectors for chunks with text-embedding-3-small for vector DBs",
    "fp_op_md2json_title": "Convert Markdown to JSON",
    "fp_op_md2json_desc": "Extract headings hierarchy, sections, lists, and tables into structured JSON",
    "fp_op_val_title": "JSON Structure Validation",
    "fp_op_val_desc": "Validate syntax, check nesting depth, and report line-by-line errors",
    "fp_op_clean_title": "Clean JSON Values",
    "fp_op_clean_desc": "Strip whitespace, prune null values, and standardize record structures",
    "fp_op_enrich_title": "Metadata Enrichment & Fingerprinting",
    "fp_op_enrich_desc": "Compute SHA-256 fingerprint, word count, categorization, and timestamps",
    "fp_op_dedup_title": "Deduplication",
    "fp_op_dedup_desc": "Remove duplicate records via SHA-256/text hashing, merge alternate sources, optimize file",
    "fp_chunk_strat_lbl": "Chunk Strategy:",
    "fp_cat_lbl": "Category (Optional):",
    "fp_cat_placeholder": "e.g., documentation, faq, policy",
    "fp_format_lbl": "Output File Format:",
    "fp_fmt_json": "Structured JSON (.json)",
    "fp_fmt_jsonl": "JSON Lines (.jsonl)",
    "fp_fmt_md": "Markdown (.md)",
    "fp_fmt_csv": "CSV (.csv)",
    "fp_fmt_txt": "Plain Text (.txt)",
    "fp_btn_run": "Run File Processing Pipeline",
    "fp_res_title": "Processing Results & Output Preview",
    "fp_res_subtitle": "Quantitative metrics, cleaned preview, and side-by-side diff",
    "fp_btn_download": "Download Output File",
    "fp_stat_in": "Input Records",
    "fp_stat_out": "Output Records",
    "fp_stat_chunks": "Produced Chunks",
    "fp_stat_vectors": "Vector Embeddings",
    "fp_stat_fixes": "Text Normalizations",
    "fp_stat_duration": "Processing Time",
    "fp_tab_output": "Final Output Preview",
    "fp_tab_diff": "Diff Changes",
    "modal_prev_title": "Extracted Document Preview",
    "modal_close": "Close window",
    "modal_url": "Page URL:",
    "modal_status": "Status:",
    "modal_engine": "Engine:",
    "modal_page_type": "Page Type:",
    "modal_wordcount": "Word Count:",
    "modal_quality": "Quality Score:",
    "modal_content_label": "Cleaned & Extracted Content:",
    "modal_btn_copy": "Copy Text",
    "modal_btn_close": "Close",
    "modal_err_title": "Process Execution Error",
    "modal_btn_dismiss": "Understood",
    "ext_loading_delay_title": "Manual delay for initial loading, spinner animations, and SPA hydration (seconds)",
    "status_crawled": "Crawled",
    "status_extracted": "Extracted",
    "status_error": "Error",
    "status_blocked": "Blocked",
    "status_blocked_page": "Blocked",
    "status_pending": "Pending",
    "status_redirect_loop": "Redirect loop",
    "status_too_many_redirects": "Too many redirects",
    "status_empty_content": "Empty content",
    "status_low_quality": "Low quality",
    "status_duplicate": "Duplicate",
    "status_in_progress": "In progress",
    "status_crawling": "Crawling...",
    "status_extracting": "Extracting...",
    "status_completed": "Completed",
    "status_failed": "Failed",
    "status_cancelled": "Cancelled",
    "status_unknown": "Unknown",
    "empty_disc_no_search": "No results match your search query",
    "empty_disc_search_hint": "Try a different search query or clear the filter.",
    "no_title": "(Untitled)",
    "view_btn": "Preview",
    "items": "items",
    "pages": "pages",
    "docs": "docs",
    "words": "words",
    "items_count_suffix": "items",
    "docs_extracted_suffix": "documents extracted",
    "no_job_active": "No active job",
    "toast_enter_root_url": "Please enter the root website URL.",
    "toast_invalid_url": "Invalid URL format (must start with http:// or https://).",
    "toast_discovery_started": "URL discovery crawl started...",
    "toast_discovery_stopped": "URL discovery crawl stopped.",
    "toast_discovery_completed": "URL discovery crawl completed successfully.",
    "toast_no_urls_selected": "No URLs selected to send.",
    "toast_urls_sent": "URLs successfully sent to Extraction tab.",
    "toast_enter_at_least_one_url": "Please enter at least one valid URL.",
    "toast_urls_added_to_queue": "new URLs added to extraction queue.",
    "toast_queue_cleared": "Extraction queue cleared.",
    "toast_extraction_started": "Content extraction started...",
    "toast_extraction_stopped": "Content extraction stopped.",
    "toast_extraction_completed": "Content extraction completed successfully.",
    "toast_retrying_failed": "Retrying failed items...",
    "toast_no_failed_to_retry": "No failed items found to retry.",
    "toast_export_preparing": "Preparing export file...",
    "toast_export_success": "Export file downloaded successfully.",
    "toast_export_no_pages": "No pages available to export.",
    "toast_export_no_job": "Extraction job ID not found.",
    "toast_pages_selected": "pages selected.",
    "toast_selection_cleared": "All selections cleared.",
    "toast_copied_to_clipboard": "Document text copied to clipboard.",
    "toast_copy_failed": "Failed to copy text.",
    "toast_llm_first": "Content extraction must be performed first.",
    "toast_no_api_key": "NEXORA_OPENAI_API_KEY is not configured in .env.",
    "toast_llm_started": "LLM RAG structuring started...",
    "toast_llm_done": "LLM structuring completed successfully.",
    "toast_chunking_started": "Text chunking started...",
    "toast_chunking_done": "Text chunking completed successfully.",
    "toast_embedding_started": "Generating vector embeddings...",
    "toast_embedding_done": "Vector embedding generation completed.",
    "toast_ai_pipeline_done": "AI pipeline execution completed.",
    "toast_file_uploading": "Uploading file...",
    "toast_file_upload_success": "uploaded successfully.",
    "toast_file_upload_failed": "Error uploading file",
    "toast_file_select_first": "Please upload a valid file first.",
    "toast_file_select_op": "Please select at least one pipeline operation.",
    "toast_file_proc_started": "Pipeline processing started...",
    "toast_file_proc_success": "File processing pipeline completed successfully.",
    "toast_file_proc_failed": "Error processing file",
    "toast_sync_error": "Status synchronization error",
    "toast_auto_chunking_first": "Auto-chunking text first to generate chunks...",
    "ai_step_pending": "Pending...",
    "ai_step_running": "Processing...",
    "ai_step_done": "Completed ✓",
    "ai_step_error": "Error",
    "ai_step_skipped": "Skipped",
    "ai_step_not_selected": "Not selected",
    "ai_step_rag_running": "Structuring with LLM...",
    "ai_step_chunk_running": "Chunking text...",
    "ai_step_embed_running": "Generating vector embeddings...",
    "ai_step_need_chunk": "Enable text chunking first",
    "prev_tag_enhanced": "Displaying structured RAG output (summaries, keywords & Q&A)",
    "prev_tag_raw": "Initial extracted documents preview (before LLM enhancement)",
    "prev_tag_waiting_extract": "Waiting for extraction",
    "prev_code_no_extract": "// No documents extracted yet. Extract pages in the Extraction tab first.",
    "prev_tag_chunks": "Displaying first 5 produced chunks ready for RAG",
    "prev_tag_waiting_chunk": "Waiting for chunking",
    "prev_code_no_chunks": "// No chunking executed yet. Click 'Run Text Chunking'.",
    "fp_output_empty": "// Empty output",
    "fp_diff_empty": "// No changes compared to original file.",
    "no_text_extracted": "⚠️ No text content extracted from this page.",
    "warnings_and_errors": "Logged warnings & errors:",
    "fp_processing": "Processing pipeline...",

    // --- Phase 3: RAG Retrieval Evaluation Studio ---
    "eval_hero_badge": "<i class=\"fa-solid fa-microscope text-primary\"></i> RAG Retrieval Intelligence & Evaluation Studio",
    "eval_title": "RAG Retrieval Evaluation, Method Comparison & Debugging",
    "eval_subtitle": "Rigorous IR benchmark metrics (Recall@K, Precision@K, MRR, nDCG@K), side-by-side Dense vs BM25 vs Hybrid comparison, and full candidate exclusion traces.",
    "eval_job_select_lbl": "Select Target Extraction/Crawl Job:",
    "eval_job_placeholder": "Job ID",
    "eval_job_select_default": "(Select from completed jobs...)",
    "eval_btn_current_job": "Active Job",
    "eval_btn_current_job_title": "Use currently active studio job",
    "eval_version_lbl": "Snapshot Version:",
    "eval_version_current": "Current Live Chunks",
    "eval_subnav_playground": "<i class=\"fa-solid fa-terminal\"></i> Playground",
    "eval_subnav_comparison": "<i class=\"fa-solid fa-columns\"></i> 3-Method Comparison",
    "eval_subnav_datasets": "<i class=\"fa-solid fa-layer-group\"></i> Datasets & QA",
    "eval_subnav_runs": "<i class=\"fa-solid fa-chart-line\"></i> Runs & Metrics",
    "eval_subnav_diff": "<i class=\"fa-solid fa-code-compare\"></i> Version Diff",
    "eval_subnav_debugger": "<i class=\"fa-solid fa-bug\"></i> Trace Debugger",
    "eval_pg_title": "Interactive Retrieval Query & Context Expansion",
    "eval_pg_badge": "Transparent Scoring & Context",
    "eval_pg_query_lbl": "Search Query / Test Question:",
    "eval_pg_query_placeholder": "Type your query or question here...",
    "eval_pg_btn_search": "<i class=\"fa-solid fa-magnifying-glass\"></i> Search",
    "eval_pg_method_lbl": "Retrieval Method:",
    "eval_pg_method_hybrid": "Hybrid (Dense + Lexical)",
    "eval_pg_method_dense": "Dense (Semantic)",
    "eval_pg_method_bm25": "BM25 (Lexical)",
    "eval_pg_topk_lbl": "Depth Cutoff (Top-K):",
    "eval_pg_alpha_lbl": "Hybrid Alpha:",
    "eval_pg_alpha_hint": "(Semantic vector weight vs lexical weight)",
        "eval_pg_minscore_hint": "Minimum relevance score cutoff threshold",
        "eval_pg_topk_hint": "Number of candidate chunks to retrieve",
        "eval_pg_params_title": "Retrieval Hyperparameters & Tuning",
    "eval_pg_minscore_lbl": "Minimum Relevance Score:",
    "eval_pg_cat_lbl": "Category Filter (Optional):",
    "eval_pg_cat_placeholder": "e.g., rag, docs",
    "eval_pg_url_lbl": "Source URL Filter (Optional):",
    "eval_pg_url_placeholder": "https://...",
    "eval_pg_expand_neighbors": "Enable Context Expansion (attach neighboring chunks)",
    "eval_pg_scale_warning": "Engineering Rule on Score Scale: Dense cosine similarity (0 to 1), normalized BM25, and Hybrid scores operate on distinct distributions; raw scores cannot be directly cross-compared without method context.",
    "eval_pg_empty_desc": "Enter a search query above and click Execute Search.",
    "eval_pg_searching": "Executing retrieval search...",
    "eval_pg_no_results": "No chunks found matching query criteria and score threshold.",
    "eval_pg_adjust_hint": "Try lowering min_score or relaxing metadata filters.",
    "eval_pg_total_results": "Returned Results:",
    "eval_pg_candidates_of": "out of",
    "eval_pg_candidates_considered": "candidates",
    "eval_pg_latency": "Latency:",
    "eval_pg_rank": "Rank",
    "eval_pg_score": "Score:",
    "eval_pg_source": "Source:",
    "eval_pg_source_file": "Document File",
    "eval_pg_chars": "Characters:",
    "eval_pg_neighbors_ctx": "Attached Neighbor Context",
    "eval_pg_chunks_unit": "chunks",
    "eval_cmp_title": "Side-by-Side 3-Method Retrieval Comparison",
    "eval_cmp_badge": "Unbiased Multi-Method Analysis",
    "eval_cmp_query_lbl": "Test Query for Side-by-Side Comparison:",
    "eval_cmp_query_placeholder": "Enter test query to compare algorithmic behaviors...",
    "eval_cmp_btn_run": "<i class=\"fa-solid fa-play\"></i> Run 3-Method Comparison",
    "eval_cmp_notice": "This comparison illustrates real behavior on your dataset. No single method is universally superior; dense embeddings capture semantic meaning while BM25 excels at exact keyword matches.",
    "eval_cmp_empty_desc": "Enter a query above to inspect and compare Dense, BM25, and Hybrid results across 3 distinct columns.",
    "eval_cmp_col_dense": "Dense Search (Semantic)",
    "eval_cmp_col_bm25": "BM25 Search (Lexical)",
    "eval_cmp_col_hybrid": "Hybrid Search (Dense + BM25)",
    "eval_cmp_bm25_subtitle": "Offline keyword search",
    "eval_cmp_hybrid_subtitle": "Weighted fusion",
    "eval_cmp_no_results": "No results found.",
    "eval_ds_title": "Evaluation Datasets & Ground Truth Management",
    "eval_ds_btn_create": "<i class=\"fa-solid fa-plus\"></i> New Dataset",
    "eval_ds_btn_import_qa": "<i class=\"fa-solid fa-wand-magic-sparkles\"></i> Import Synthetic QA",
    "eval_ds_select_lbl": "Select Evaluation Dataset:",
    "eval_ds_select_loading": "(Loading datasets...)",
    "eval_ds_select_none": "No datasets created yet",
    "eval_ds_btn_delete_title": "Delete this dataset",
    "eval_ds_samples_title": "Test Samples & Reference Ground Truth:",
    "eval_ds_btn_add_sample": "<i class=\"fa-solid fa-plus\"></i> Add Manual Question",
    "eval_ds_stat_total": "Total Samples:",
    "eval_ds_stat_has_gt": "With Ground Truth:",
    "eval_ds_stat_reviewed": "Human Reviewed:",
    "eval_ds_stat_created": "Created:",
    "eval_th_id": "Sample ID",
    "eval_th_question": "Question",
    "eval_th_origin": "Origin",
    "eval_th_gt": "Ground Truth",
    "eval_th_status": "Review Status",
    "eval_th_actions": "Actions",
    "eval_ds_table_empty": "No samples in this dataset yet. Use the buttons above to add manual questions or import synthetic QA pairs.",
    "eval_origin_ai": "AI Synthetic",
    "eval_origin_real": "Real User",
    "eval_origin_manual": "Manual",
    "eval_gt_has": "Provided",
    "eval_gt_none": "Unlabeled",
    "eval_review_verified": "Verified",
    "eval_review_pending": "Unreviewed",
    "eval_btn_review": "Review",
    "eval_btn_delete": "Delete",
    "eval_run_title": "Execute IR Benchmark Run & Calculate Metrics",
    "eval_run_badge": "Deterministic Math · No Fake Numbers",
    "eval_run_target_ds": "Target Evaluation Dataset:",
    "eval_run_method": "Retrieval Search Method:",
    "eval_run_method_hybrid": "Hybrid (Dense + Lexical)",
    "eval_run_method_bm25": "BM25 (Offline Lexical)",
    "eval_run_method_dense": "Dense (Semantic)",
    "eval_run_topk": "Metric Cutoff Depth (Top-K):",
    "eval_run_alpha": "Hybrid Alpha:",
    "eval_run_btn_execute": "<i class=\"fa-solid fa-play\"></i> Execute IR Benchmark Run",
    "eval_run_empty_desc": "Select a dataset and configuration above, then click Execute IR Benchmark.",
    "eval_run_running": "Calculating mathematical IR metrics across test samples...",
    "eval_run_err_insufficient_gt": "Cannot compute numerical IR metrics:",
    "eval_run_err_no_gt_desc": "No human-verified ground truth labels found in this dataset.",
    "eval_metric_recall": "Recall@K (Coverage)",
    "eval_metric_precision": "Precision@K (Precision)",
    "eval_metric_mrr": "MRR (Mean Reciprocal Rank)",
    "eval_metric_hit": "Hit Rate",
    "eval_metric_ndcg": "nDCG@K",
    "eval_metric_req_gt": "Requires Ground Truth",
    "eval_metric_req_mrr": "First relevant hit speed",
    "eval_metric_req_hit": "At least 1 relevant hit in Top-K",
    "eval_metric_req_graded": "Requires graded relevance labels",
    "eval_run_results_title": "Per-Question Benchmark Results",
    "eval_th_first_rank": "First Hit Rank",
    "eval_th_hit": "Hit",
    "eval_diff_title": "Pipeline Version Diff & Retrieval Quality Tracking",
    "eval_diff_badge": "Query Win / Loss Tracking",
    "eval_diff_run_a": "Baseline Run (Run A):",
    "eval_diff_run_b": "Target Run (Run B):",
    "eval_diff_btn_compare": "<i class=\"fa-solid fa-scale-balanced\"></i> Calculate Metric Deltas & Diff",
    "eval_diff_empty_desc": "Select two benchmark runs to compute IR metric deltas and inspect query transitions (wins vs losses).",
    "eval_diff_improved": "Improved Queries (Wins)",
    "eval_diff_regressed": "Regressed Queries (Losses)",
    "eval_diff_no_items": "No queries in this category.",
    "eval_diff_rank_label": "Rank:",
    "eval_diff_out_of_k": "Out of K",
    "eval_diff_recall_delta": "Recall Delta:",
    "eval_dbg_title": "Step-by-Step Retrieval Debugger & Exclusion Trace",
    "eval_dbg_badge": "Transparent Glass-Box Diagnostics",
    "eval_dbg_query_lbl": "Diagnostic Query for Pipeline Trace:",
    "eval_dbg_query_placeholder": "Enter query for step-by-step pipeline debugging...",
    "eval_dbg_btn_run": "<i class=\"fa-solid fa-bug\"></i> Trace Pipeline Execution",
    "eval_dbg_empty_desc": "Enter a test query to visualize tokenization, metadata filtering, min-score thresholding, and final candidate ranking.",
    "eval_dbg_tracing": "Tracing pipeline execution steps and candidate exclusions...",
    "eval_dbg_warn_title": "System Diagnostic Warnings & Advisory:",
    "eval_dbg_step1_title": "Step 1: Query Analysis & Tokenization",
    "eval_dbg_step1_norm": "Normalized Query Text:",
    "eval_dbg_step1_tokens": "Extracted Tokens:",
    "eval_dbg_step2_title": "Step 2: Metadata Filtering",
    "eval_dbg_step2_excluded": "Excluded:",
    "eval_dbg_step2_remaining": "Remaining:",
    "eval_dbg_step2_total": "Total initial chunks in dataset:",
    "eval_dbg_step2_reasons": "Sample metadata exclusion reasons:",
    "eval_dbg_step2_none_excluded": "✓ No chunks were excluded by metadata filters.",
    "eval_dbg_step3_title": "Step 3: Scoring & Min Score Threshold",
    "eval_dbg_step3_excluded": "Excluded below threshold:",
    "eval_dbg_step3_sample": "Sample chunks excluded below score threshold:",
    "eval_dbg_step3_all_passed": "✓ All candidates met the minimum score threshold.",
    "eval_dbg_step4_title": "Step 4: Context Expansion Status",
    "eval_dbg_step4_enabled": "Enabled",
    "eval_dbg_step4_disabled": "Disabled",
    "eval_dbg_step4_attached": "Neighbor chunks attached to results:",
    "eval_dbg_step5_title": "Step 5: Final Ranked Candidates",
    "eval_dbg_step5_completed": "Retrieval Complete",
    "eval_modal_cd_title": "Create New Evaluation Dataset",
    "eval_modal_cd_name_lbl": "Dataset Name:",
    "eval_modal_cd_name_placeholder": "e.g., Legal Q&A Benchmark v1",
    "eval_modal_cd_desc_lbl": "Description & Test Scenario (optional):",
    "eval_modal_cd_desc_placeholder": "Brief description of questions and domain coverage...",
    "eval_modal_cd_btn_cancel": "Cancel",
    "eval_modal_cd_btn_confirm": "Create Dataset",
    "eval_modal_as_title": "Add New Evaluation Question",
    "eval_modal_as_query_lbl": "Query / Test Question:",
    "eval_modal_as_query_placeholder": "Enter clear question or search phrase...",
    "eval_modal_as_chunks_lbl": "Expected Relevant Chunk IDs (comma separated):",
    "eval_modal_as_chunks_placeholder": "e.g., chunk_1, chunk_3",
    "eval_modal_as_urls_lbl": "Expected Valid Source URLs (comma separated):",
    "eval_modal_as_urls_placeholder": "https://example.com/article",
    "eval_modal_as_origin_lbl": "Question Origin:",
    "eval_modal_as_origin_manual": "Manual Expert Crafted",
    "eval_modal_as_origin_real": "Real User Production Query",
    "eval_modal_as_origin_llm": "AI Generated (Synthetic)",
    "eval_modal_as_notes_lbl": "Technical Notes / Test Case:",
    "eval_modal_as_notes_placeholder": "Notes regarding this scenario...",
    "eval_modal_as_verified": "Ground truth labels verified by human expert (Human Verified Ground Truth)",
    "eval_modal_as_btn_cancel": "Cancel",
    "eval_modal_as_btn_confirm": "Save Sample",
    "eval_modal_rv_title": "Human Ground Truth & Relevance Review",
    "eval_modal_rv_query_lbl": "Question:",
    "eval_modal_rv_chunks_lbl": "Relevant Chunk IDs (comma separated):",
    "eval_modal_rv_urls_lbl": "Valid Source URLs (comma separated):",
    "eval_modal_rv_graded_lbl": "Graded Relevance Map (JSON for nDCG):",
    "eval_modal_rv_graded_hint": "2 = Highly relevant, 1 = Relevant, 0 = Irrelevant",
    "eval_modal_rv_notes_lbl": "Expert Reviewer Notes:",
    "eval_modal_rv_verified": "Mark as officially human-reviewed ground truth",
    "eval_modal_rv_btn_cancel": "Cancel",
    "eval_modal_rv_btn_confirm": "Save Review Labels"
  
};

const I18N = {
  "en": I18N_EN,
  "fa": I18N_EN
};

/**
 * Get translated text for given key with fallback
 * @param {string} key
 * @param {string} [fallback]
 * @returns {string}
 */
function t(key, fallback = '') {
    const lang = state.currentLang || 'en';
    if (I18N[lang] && I18N[lang][key] !== undefined) {
        return I18N[lang][key];
    }
    return fallback || key;
}

/**
 * Switch active application language (fa <-> en)
 * @param {string} lang
 */
// Expose global language switch handlers for inline onclick and external callers
window.setAppLanguage = function(lang) {
    setLanguage(lang);
};
window.toggleAppLanguage = function() {
    const nextLang = (state.currentLang === 'fa') ? 'en' : 'fa';
    setLanguage(nextLang);
};

function setLanguage(lang) {
    lang = 'en';
    state.currentLang = lang;
    try {
        localStorage.setItem('nexora_lang', lang);
    } catch (_) {}

    const html = document.documentElement;
    html.setAttribute('lang', lang);
    html.setAttribute('dir', 'ltr');

    // Update segmented language pill buttons
    const btnFa = document.getElementById('lang-btn-fa');
    const btnEn = document.getElementById('lang-btn-en');
    if (btnFa) {
        btnFa.classList.toggle('active', lang === 'fa');
        btnFa.setAttribute('aria-pressed', lang === 'fa' ? 'true' : 'false');
    }
    if (btnEn) {
        btnEn.classList.toggle('active', lang === 'en');
        btnEn.setAttribute('aria-pressed', lang === 'en' ? 'true' : 'false');
    }

    // Legacy toggle button if present
    const langBtnText = document.getElementById('lang-switch-text');
    const langBtn = document.getElementById('btn-toggle-lang');
    if (langBtnText) {
        // Language selector removed
    }
    if (langBtn) {
        // Language selector removed
    }

    // Update elements with data-i18n
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const k = el.getAttribute('data-i18n');
        if (I18N[lang] && I18N[lang][k] !== undefined) {
            const val = I18N[lang][k];
            if (val.includes('<') && val.includes('>')) {
                el.innerHTML = val;
            } else {
                el.textContent = val;
            }
        }
    });

    // Update elements with data-i18n-placeholder
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
        const k = el.getAttribute('data-i18n-placeholder');
        if (I18N[lang] && I18N[lang][k] !== undefined) {
            el.placeholder = I18N[lang][k];
        }
    });

    // Update elements with data-i18n-title
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
        const k = el.getAttribute('data-i18n-title');
        if (I18N[lang] && I18N[lang][k] !== undefined) {
            el.title = I18N[lang][k];
        }
    });

    // Update elements with data-i18n-aria-label
    document.querySelectorAll('[data-i18n-aria-label]').forEach(el => {
        const k = el.getAttribute('data-i18n-aria-label');
        if (I18N[lang] && I18N[lang][k] !== undefined) {
            el.setAttribute('aria-label', I18N[lang][k]);
        }
    });

    // Re-render dynamic components
    if (typeof renderDiscoveryResults === 'function' && state.discoveredPages) {
        renderDiscoveryResults(filterPages(state.discoveredPages, state.searchQuery));
    }
    if (typeof renderExtractionResults === 'function' && state.extractedDocuments) {
        renderExtractionResults(state.extractedDocuments);
    }
    if (typeof renderExtractionUrlList === 'function') {
        renderExtractionUrlList();
    }
    if (typeof updateSelectedCounter === 'function') {
        updateSelectedCounter();
    }
    if (typeof window.reRenderEvalStudio === 'function') {
        window.reRenderEvalStudio();
    }
    if (typeof updateAIStudioInfo === 'function') {
        updateAIStudioInfo();
    }
}

// ============================================================================
// 2. API Client
// ============================================================================
const api = {
    /**
     * Start Discovery job
     * @param {Object} config 
     * @returns {Promise<Object>}
     */
    async startDiscovery(config) {
        const response = await fetch('/api/discovery/start', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify(config)
        });

        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || errData.message || `Error starting URL discovery (${response.status})`);
        }
        const data = await response.json();
        if (data && data.data && data.data.job_id && !data.job_id) {
            data.job_id = data.data.job_id;
        }
        return data;
    },

    /**
     * Get Discovery job status
     * @param {string} jobId 
     * @returns {Promise<Object>}
     */
    async getDiscoveryStatus(jobId) {
        const response = await fetch(`/api/discovery/status/${encodeURIComponent(jobId)}`, {
            method: 'GET',
            headers: {
                'Accept': 'application/json'
            }
        });

        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || errData.message || `Error fetching discovery status (${response.status})`);
        }
        return await response.json();
    },

    /**
     * Cancel Discovery job
     * @param {string} jobId 
     * @returns {Promise<Object>}
     */
    async cancelDiscovery(jobId) {
        const response = await fetch(`/api/discovery/cancel/${encodeURIComponent(jobId)}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
        });

        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || errData.message || `Error cancelling discovery (${response.status})`);
        }
        return await response.json();
    },

    /**
     * Start Extraction job
     * @param {Object} config 
     * @returns {Promise<Object>}
     */
    async startExtraction(config) {
        const response = await fetch('/api/extraction/start', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify(config)
        });

        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || errData.message || `Error starting content extraction (${response.status})`);
        }
        const data = await response.json();
        if (data && data.data && data.data.job_id && !data.job_id) {
            data.job_id = data.data.job_id;
        }
        return data;
    },

    /**
     * Get Extraction job status
     * @param {string} jobId 
     * @returns {Promise<Object>}
     */
    async getExtractionStatus(jobId) {
        const response = await fetch(`/api/extraction/status/${encodeURIComponent(jobId)}`, {
            method: 'GET',
            headers: {
                'Accept': 'application/json'
            }
        });

        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || errData.message || `Error fetching extraction status (${response.status})`);
        }
        return await response.json();
    },

    /**
     * Cancel Extraction job
     * @param {string} jobId 
     * @returns {Promise<Object>}
     */
    async cancelExtraction(jobId) {
        const response = await fetch(`/api/extraction/cancel/${encodeURIComponent(jobId)}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
        });

        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || errData.message || `Error cancelling extraction (${response.status})`);
        }
        return await response.json();
    },

    /**
     * Retry Failed items in Extraction job
     * @param {string} jobId 
     * @returns {Promise<Object>}
     */
    async retryFailed(jobId) {
        const response = await fetch(`/api/extraction/retry/${encodeURIComponent(jobId)}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
        });

        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || errData.message || `Error retrying failed items (${response.status})`);
        }
        const data = await response.json();
        if (data && data.data && data.data.job_id && !data.job_id) {
            data.job_id = data.data.job_id;
        }
        return data;
    },

    /**
     * Export extracted documents
     * @param {string} jobId 
     * @param {string} format ('json' | 'jsonl' | 'markdown' | 'text')
     * @param {boolean} deduplicate
     * @returns {Promise<Blob>}
     */
    async exportDocuments(jobId, format, deduplicate = false) {
        const response = await fetch('/api/export/download', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                job_id: jobId,
                format: format,
                deduplicate: deduplicate
            })
        });

        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || errData.message || `Error fetching export file (${response.status})`);
        }
        return await response.blob();
    }
};

// ============================================================================
// 3. Tab Management
// ============================================================================
/**
 * Switch active visible tab between 'discover' and 'extract'
 * @param {string} tabName 
 */
function switchTab(tabName) {
    if (state.activeTab === tabName) return;

    state.activeTab = tabName;

    // Toggle Tab Buttons
    document.querySelectorAll('.tab-button').forEach(btn => {
        const isTarget = btn.getAttribute('data-tab') === tabName;
        btn.classList.toggle('active', isTarget);
        btn.setAttribute('aria-selected', isTarget ? 'true' : 'false');
    });

    // Toggle Tab Content
    document.querySelectorAll('.tab-content').forEach(content => {
        const isTarget = content.id === `tab-content-${tabName}`;
        content.classList.toggle('active', isTarget);
        content.classList.toggle('hidden', !isTarget);
    });

    if (tabName === 'eval' && typeof window.onEvalTabActivated === 'function') {
        window.onEvalTabActivated();
    }

    // Update Topbar Active View Title
    const topbarTitle = document.getElementById('topbar-active-tab-title');
    if (topbarTitle) {
        const tabKeyMap = {
            'discover': 'nav_discover',
            'extract': 'nav_extract',
            'ai': 'nav_ai',
            'files': 'nav_files',
            'eval': 'nav_eval'
        };
        const key = tabKeyMap[tabName] || 'nav_discover';
        topbarTitle.setAttribute('data-i18n', key);
        if (typeof t === 'function') {
            topbarTitle.textContent = t(key);
        }
    }

    // Dismiss mobile sidebar drawer if open
    const sidebar = document.getElementById('app-sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    if (sidebar && sidebar.classList.contains('sidebar-open')) {
        sidebar.classList.remove('sidebar-open');
        if (overlay) overlay.classList.remove('active');
    }
}

// ============================================================================
// 4. Discovery Functions
// ============================================================================
/**
 * Start the website discovery crawl
 */
async function startDiscovery() {
    if (state.isDiscovering) return;

    const rootUrlInput = document.getElementById('input-root-url');
    const rootUrl = rootUrlInput ? rootUrlInput.value.trim() : '';

    if (!rootUrl) {
        showToast('Please enter the root website URL.', 'warning');
        if (rootUrlInput) rootUrlInput.focus();
        return;
    }

    // Basic URL validation
    try {
        new URL(rootUrl);
    } catch (_) {
        showToast('The entered URL is invalid (must start with http:// or https://).', 'error');
        if (rootUrlInput) rootUrlInput.focus();
        return;
    }

    // Collect settings
    const maxDepth = parseInt(document.getElementById('input-max-depth')?.value || '3', 10);
    const maxPages = parseInt(document.getElementById('input-max-pages')?.value || '100', 10);
    const timeout = parseInt(document.getElementById('input-timeout')?.value || '30', 10);
    const concurrency = parseInt(document.getElementById('input-concurrency')?.value || '5', 10);
    const delay = parseFloat(document.getElementById('input-delay')?.value || '0.5');
    const allowSubdomains = document.getElementById('check-allow-subdomains')?.checked || false;
    const keepQueryParams = document.getElementById('check-keep-query-params')?.checked || false;
    const useSitemap = document.getElementById('check-use-sitemap')?.checked || false;
    const enableBrowserFallback = document.getElementById('check-browser-fallback') ? document.getElementById('check-browser-fallback').checked : true;
    const pathPrefix = document.getElementById('input-path-prefix')?.value.trim() || '';

    const includePatternsRaw = document.getElementById('input-include-patterns')?.value || '';
    const excludePatternsRaw = document.getElementById('input-exclude-patterns')?.value || '';

    const includePatterns = includePatternsRaw.split('\n').map(s => s.trim()).filter(Boolean);
    const excludePatterns = excludePatternsRaw.split('\n').map(s => s.trim()).filter(Boolean);

    const config = {
        root_url: rootUrl,
        max_depth: maxDepth,
        max_pages: maxPages,
        timeout: timeout,
        concurrency: concurrency,
        delay: delay,
        allow_subdomains: allowSubdomains,
        keep_query_params: keepQueryParams,
        use_sitemap: useSitemap,
        enable_browser_fallback: enableBrowserFallback,
        include_patterns: includePatterns,
        exclude_patterns: excludePatterns,
        path_prefix: pathPrefix
    };

    // Update UI for starting
    state.isDiscovering = true;
    toggleDiscoveryControls(true);
    setDiscoveryStatusBadge('running', 'Processing...');
    showToast('URL discovery process started.', 'info');

    try {
        const response = await api.startDiscovery(config);
        if (response && response.success === false) {
            throw new Error(response.message || 'Failed to start URL discovery');
        }
        const jobId = response.data?.job_id || response.job_id || response.id;

        if (!jobId) {
            throw new Error('No job ID was returned from server.');
        }

        state.discoveryJobId = jobId;
        const jobIdEl = document.getElementById('discovery-job-id');
        if (jobIdEl) jobIdEl.textContent = jobId;

        // Reset previous discoveries
        state.discoveredPages = [];
        state.selectedUrls.clear();
        updateSelectedCounter();
        renderDiscoveryResults([]);

        // Start polling for progress
        startPolling(jobId, 'discovery', 2000);

    } catch (error) {
        state.isDiscovering = false;
        toggleDiscoveryControls(false);
        setDiscoveryStatusBadge('failed', 'Failed to start');
        showToast(error.message, 'error');
        showErrorModal('Error Starting Discovery', error.message);
    }
}

/**
 * Cancel the active discovery job
 */
async function cancelDiscovery() {
    if (!state.discoveryJobId || !state.isDiscovering) return;

    try {
        showToast('Discovery stop request sent...', 'warning');
        await api.cancelDiscovery(state.discoveryJobId);
        stopPolling();
        state.isDiscovering = false;
        toggleDiscoveryControls(false);
        setDiscoveryStatusBadge('cancelled', 'Stopped');
        showToast('URL discovery was stopped by user.', 'info');
    } catch (error) {
        showToast(error.message, 'error');
    }
}

/**
 * Update discovery progress bar, stats, and results table
 * @param {Object} statusData 
 */
function updateDiscoveryProgress(statusData) {
    if (!statusData) return;

    const totalDiscovered = statusData.total_discovered ?? statusData.discovered ?? statusData.total ?? (Array.isArray(statusData.pages) ? statusData.pages.length : 0);
    const crawled = statusData.crawled ?? statusData.total_crawled ?? statusData.completed ?? 0;
    const failed = statusData.failed ?? statusData.total_failed ?? 0;
    const jobStatus = (statusData.status || 'running').toLowerCase();

    // Update stat numbers
    const totalEl = document.getElementById('stat-discovery-total');
    const crawledEl = document.getElementById('stat-discovery-crawled');
    const failedEl = document.getElementById('stat-discovery-failed');

    if (totalEl) totalEl.textContent = totalDiscovered.toLocaleString('fa-IR');
    if (crawledEl) crawledEl.textContent = crawled.toLocaleString('fa-IR');
    if (failedEl) failedEl.textContent = failed.toLocaleString('fa-IR');

    // Update badge count on tab header
    const tabCountBadge = document.getElementById('discover-badge-count');
    if (tabCountBadge) tabCountBadge.textContent = totalDiscovered;

    // Calculate percentage
    let percent = 0;
    if (typeof statusData.progress === 'number') {
        percent = Math.min(100, Math.max(0, Math.round(statusData.progress)));
    } else if (totalDiscovered > 0) {
        percent = Math.min(100, Math.round(((crawled + failed) / totalDiscovered) * 100));
    }

    const progressBar = document.getElementById('discovery-progress-bar');
    const progressText = document.getElementById('discovery-progress-text');
    if (progressBar) progressBar.style.width = `${percent}%`;
    if (progressText) progressText.textContent = `${percent}%`;

    // Update pages table
    const pages = statusData.pages || statusData.results || [];
    if (Array.isArray(pages) && pages.length > 0) {
        state.discoveredPages = pages;
        renderDiscoveryResults(filterPages(pages, state.searchQuery));
    }

    // Check completion status
    if (['completed', 'finished', 'done', 'success'].includes(jobStatus)) {
        stopPolling();
        state.isDiscovering = false;
        toggleDiscoveryControls(false);
        setDiscoveryStatusBadge('success', 'Completed');
        if (progressBar) progressBar.style.width = '100%';
        if (progressText) progressText.textContent = '100%';
        showToast(`Discovery completed. ${totalDiscovered} pages discovered.`, 'success');
    } else if (['failed', 'error'].includes(jobStatus)) {
        stopPolling();
        state.isDiscovering = false;
        toggleDiscoveryControls(false);
        setDiscoveryStatusBadge('failed', 'Process Error');
        showToast(statusData.error || 'An error occurred during URL discovery.', 'error');
    } else if (['cancelled', 'stopped'].includes(jobStatus)) {
        stopPolling();
        state.isDiscovering = false;
        toggleDiscoveryControls(false);
        setDiscoveryStatusBadge('cancelled', 'Stopped');
    } else {
        setDiscoveryStatusBadge('running', 'Discovering...');
    }
}

/**
 * Render Discovery results table
 * @param {Array<Object>} pages 
 */
function renderDiscoveryResults(pages) {
    const tbody = document.getElementById('discovery-table-body');
    const showingCountEl = document.getElementById('discovery-showing-count');
    const totalCountEl = document.getElementById('discovery-total-count');

    if (totalCountEl) totalCountEl.textContent = state.discoveredPages.length.toLocaleString('fa-IR');
    if (showingCountEl) showingCountEl.textContent = pages.length.toLocaleString('fa-IR');

    if (!tbody) return;

    if (!pages || pages.length === 0) {
        tbody.innerHTML = `
            <tr class="empty-state-row">
                <td colspan="6">
                    <div class="empty-state">
                        <div class="empty-icon"><i class="fa-solid fa-folder-open"></i></div>
                        <h4>${state.searchQuery ? t('empty_disc_no_search', 'No results matching search') : t('empty_disc_title', 'No pages discovered yet')}</h4>
                        <p>${state.searchQuery ? t('empty_disc_search_hint', 'Change your search term or clear the filter.') : t('empty_disc_desc', 'Enter the root URL and start discovery.')}</p>
                    </div>
                </td>
            </tr>
        `;
        return;
    }

    let rowsHtml = '';
    pages.forEach(page => {
        const url = page.url || '';
        const title = page.title || '(Untitled)';
        const pageStatus = (page.status || 'pending').toLowerCase();
        const source = page.source || 'crawl';
        const depth = page.depth !== undefined ? page.depth : '-';
        const isChecked = state.selectedUrls.has(url);

        let badgeClass = 'badge-secondary';
        let statusLabel = pageStatus;

        if (['success', 'completed', 'crawled', '200', 'ok'].includes(pageStatus)) {
            badgeClass = 'badge-success';
            statusLabel = t('status_crawled', 'Crawled');
        } else if (pageStatus === 'redirect_loop') {
            badgeClass = 'badge-warning';
            statusLabel = t('status_redirect_loop', 'Redirect Loop');
        } else if (pageStatus === 'too_many_redirects') {
            badgeClass = 'badge-warning';
            statusLabel = t('status_too_many_redirects', 'Too Many Redirects');
        } else if (['failed', 'error', '404', '500'].includes(pageStatus)) {
            badgeClass = 'badge-failed';
            statusLabel = t('status_error', 'Error');
        } else if (['blocked', '403', 'robot'].includes(pageStatus)) {
            badgeClass = 'badge-blocked';
            statusLabel = t('status_blocked', 'Blocked');
        } else if (['pending', 'queued', 'in_progress', '0'].includes(pageStatus)) {
            badgeClass = 'badge-pending';
            statusLabel = t('status_pending', 'Pending');
        }

        rowsHtml += `
            <tr data-url="${escapeHtml(url)}">
                <td class="col-checkbox">
                    <input type="checkbox" class="row-checkbox discovery-row-checkbox" data-url="${escapeHtml(url)}" ${isChecked ? 'checked' : ''} />
                </td>
                <td class="col-url" title="${escapeHtml(url)}">
                    <a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(url)}</a>
                </td>
                <td class="col-title" title="${escapeHtml(title)}">${escapeHtml(title)}</td>
                <td class="col-status">
                    <span class="badge ${badgeClass}">${escapeHtml(statusLabel)}</span>
                </td>
                <td class="col-source">
                    <span class="source-tag">${escapeHtml(source)}</span>
                </td>
                <td class="col-depth">${depth}</td>
            </tr>
        `;
    });

    tbody.innerHTML = rowsHtml;

    // Attach row checkbox event listeners
    tbody.querySelectorAll('.discovery-row-checkbox').forEach(cb => {
        cb.addEventListener('change', (e) => {
            const rowUrl = e.target.getAttribute('data-url');
            if (rowUrl) toggleSelection(rowUrl, e.target.checked);
        });
    });

    updateHeaderCheckbox();
}

/**
 * Filter pages array based on query text
 * @param {Array<Object>} pages 
 * @param {string} query 
 * @returns {Array<Object>}
 */
function filterPages(pages, query) {
    if (!query) return pages;
    const lowerQuery = query.toLowerCase();
    return pages.filter(p => {
        const u = (p.url || '').toLowerCase();
        const t = (p.title || '').toLowerCase();
        return u.includes(lowerQuery) || t.includes(lowerQuery);
    });
}

/**
 * Toggle enable/disable discovery controls
 * @param {boolean} isRunning 
 */
function toggleDiscoveryControls(isRunning) {
    const btnStart = document.getElementById('btn-start-discovery');
    const btnCancel = document.getElementById('btn-cancel-discovery');
    const rootUrlInput = document.getElementById('input-root-url');

    if (btnStart) {
        btnStart.disabled = isRunning;
        btnStart.classList.toggle('hidden', isRunning);
    }
    if (btnCancel) {
        btnCancel.classList.toggle('hidden', !isRunning);
    }
    if (rootUrlInput) {
        rootUrlInput.disabled = isRunning;
    }
}

/**
 * Set status badge text and style for discovery
 * @param {string} statusType ('running' | 'success' | 'failed' | 'cancelled')
 * @param {string} label 
 */
function setDiscoveryStatusBadge(statusType, label) {
    const badge = document.getElementById('discovery-status-badge');
    if (!badge) return;

    badge.className = 'badge';
    if (statusType === 'running') badge.classList.add('badge-pending');
    else if (statusType === 'success') badge.classList.add('badge-success');
    else if (statusType === 'failed') badge.classList.add('badge-failed');
    else if (statusType === 'cancelled') badge.classList.add('badge-blocked');
    else badge.classList.add('badge-secondary');

    badge.textContent = label;
}

// ============================================================================
// 5. Selection Functions
// ============================================================================
/**
 * Select all currently filtered pages
 */
function selectAll() {
    const filtered = filterPages(state.discoveredPages, state.searchQuery);
    filtered.forEach(page => {
        if (page.url) state.selectedUrls.add(page.url);
    });

    document.querySelectorAll('.discovery-row-checkbox').forEach(cb => {
        cb.checked = true;
    });

    updateSelectedCounter();
    updateHeaderCheckbox();
    showToast(`${filtered.length} pages selected.`, 'info');
}

/**
 * Deselect all pages
 */
function deselectAll() {
    state.selectedUrls.clear();

    document.querySelectorAll('.discovery-row-checkbox').forEach(cb => {
        cb.checked = false;
    });

    updateSelectedCounter();
    updateHeaderCheckbox();
    showToast('All page selections cleared.', 'info');
}

/**
 * Toggle individual URL selection
 * @param {string} url 
 * @param {boolean} forceCheck 
 */
function toggleSelection(url, forceCheck) {
    if (!url) return;
    if (forceCheck !== undefined) {
        if (forceCheck) state.selectedUrls.add(url);
        else state.selectedUrls.delete(url);
    } else {
        if (state.selectedUrls.has(url)) state.selectedUrls.delete(url);
        else state.selectedUrls.add(url);
    }

    updateSelectedCounter();
    updateHeaderCheckbox();
}

/**
 * Update selected count badges across UI
 */
function updateSelectedCounter() {
    const count = state.selectedUrls.size;
    const statSelectedEl = document.getElementById('stat-discovery-selected');
    const sendCountEl = document.getElementById('btn-send-count');
    const btnSend = document.getElementById('btn-send-to-extraction');

    if (statSelectedEl) statSelectedEl.textContent = count.toLocaleString(state.currentLang === 'fa' ? 'fa-IR' : 'en-US');
    if (sendCountEl) sendCountEl.textContent = count;
    if (btnSend) btnSend.disabled = (count === 0);
}

/**
 * Update header checkbox state based on visible row selections
 */
function updateHeaderCheckbox() {
    const headerCb = document.getElementById('header-discovery-checkbox');
    if (!headerCb) return;

    const visibleCheckboxes = document.querySelectorAll('.discovery-row-checkbox');
    if (visibleCheckboxes.length === 0) {
        headerCb.checked = false;
        headerCb.indeterminate = false;
        return;
    }

    let checkedCount = 0;
    visibleCheckboxes.forEach(cb => {
        if (cb.checked) checkedCount++;
    });

    if (checkedCount === 0) {
        headerCb.checked = false;
        headerCb.indeterminate = false;
    } else if (checkedCount === visibleCheckboxes.length) {
        headerCb.checked = true;
        headerCb.indeterminate = false;
    } else {
        headerCb.checked = false;
        headerCb.indeterminate = true;
    }
}

/**
 * Transfer selected URLs to the Extraction tab and switch view
 */
function sendToExtraction() {
    if (state.selectedUrls.size === 0) {
        showToast('No URLs selected to send.', 'warning');
        return;
    }

    // Add selected URLs to the extraction set
    state.selectedUrls.forEach(url => {
        state.extractionUrls.add(url);
    });

    renderExtractionUrlList();
    showToast(`${state.selectedUrls.size} URLs successfully added to extraction.`, 'success');

    // Switch to Extraction tab
    switchTab('extract');
}

// ============================================================================
// 6. Extraction Functions
// ============================================================================
/**
 * Add URLs typed or pasted into the manual textarea
 */
function addManualExtractionUrls() {
    const textarea = document.getElementById('input-extraction-urls-textarea');
    if (!textarea) return;

    const parsedUrls = parseUrlsFromTextarea(textarea.value);
    if (parsedUrls.length === 0) {
        showToast('Please enter at least one valid URL.', 'warning');
        return;
    }

    let addedCount = 0;
    parsedUrls.forEach(url => {
        if (!state.extractionUrls.has(url)) {
            state.extractionUrls.add(url);
            addedCount++;
        }
    });

    textarea.value = '';
    const badge = document.getElementById('urls-input-count');
    if (badge) badge.textContent = '0 items';

    renderExtractionUrlList();
    showToast(`${addedCount} new URLs added to extraction list.`, 'success');
}

/**
 * Remove an individual URL from the extraction queue
 * @param {string} url 
 */
function removeExtractionUrl(url) {
    if (state.extractionUrls.has(url)) {
        state.extractionUrls.delete(url);
        renderExtractionUrlList();
    }
}

/**
 * Clear all selected URLs in the extraction queue
 */
function clearAllExtractionUrls() {
    if (state.extractionUrls.size === 0) return;
    state.extractionUrls.clear();
    renderExtractionUrlList();
    showToast('Extraction URL list cleared completely.', 'info');
}

/**
 * Render the list of URLs queued for extraction
 */
function renderExtractionUrlList() {
    const container = document.getElementById('selected-urls-list-container');
    const countBadge = document.getElementById('selected-urls-count');
    const tabExtractBadge = document.getElementById('extract-badge-count');

    const total = state.extractionUrls.size;
    if (countBadge) countBadge.textContent = `${total} URLs`;
    if (tabExtractBadge) tabExtractBadge.textContent = total;

    if (!container) return;

    if (total === 0) {
        container.innerHTML = `<div class="empty-list-notice">No URLs added for extraction yet. You can send URLs from the Discovery tab or enter them manually.</div>`;
        return;
    }

    let html = '';
    state.extractionUrls.forEach(url => {
        html += `
            <div class="url-item-chip" title="${escapeHtml(url)}">
                <span class="url-item-text">${escapeHtml(url)}</span>
                <button type="button" class="btn-remove-url" data-url="${escapeHtml(url)}" title="Remove this URL">
                    <i class="fa-solid fa-xmark"></i>
                </button>
            </div>
        `;
    });

    container.innerHTML = html;

    // Attach remove handlers
    container.querySelectorAll('.btn-remove-url').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const targetUrl = btn.getAttribute('data-url');
            if (targetUrl) removeExtractionUrl(targetUrl);
        });
    });
}

/**
 * Start the content extraction process
 */
async function startExtraction() {
    if (state.isExtracting) return;

    // If textarea has unadded URLs, try to add them automatically
    const textarea = document.getElementById('input-extraction-urls-textarea');
    if (textarea && textarea.value.trim()) {
        const extraUrls = parseUrlsFromTextarea(textarea.value);
        extraUrls.forEach(u => state.extractionUrls.add(u));
        textarea.value = '';
        renderExtractionUrlList();
    }

    if (state.extractionUrls.size === 0) {
        showToast('Please add at least one URL for extraction first.', 'warning');
        return;
    }

    const category = document.getElementById('input-extraction-category')?.value.trim() || '';
    const strategy = document.getElementById('select-extraction-strategy')?.value || 'auto';
    const crawlMode = document.getElementById('select-crawl-mode')?.value || 'single_page';
    const renderMode = document.getElementById('select-render-mode')?.value || 'auto';
    const minQuality = parseInt(document.getElementById('input-min-quality-score')?.value || '40', 10);
    const concurrency = parseInt(document.getElementById('input-extraction-concurrency')?.value || '5', 10);
    const loadingDelayVal = parseFloat(document.getElementById('input-loading-delay')?.value || '0');
    const waitSelector = document.getElementById('input-wait-selector')?.value.trim() || '';

    const config = {
        urls: Array.from(state.extractionUrls),
        category: category,
        extraction_strategy: strategy,
        extractor: strategy,
        strategy: strategy,
        crawl_mode: crawlMode,
        render_mode: renderMode,
        min_quality_score: minQuality,
        max_concurrency: concurrency,
        concurrency: concurrency,
        loading_delay: isNaN(loadingDelayVal) ? 0.0 : loadingDelayVal,
        wait_for_selector: waitSelector || null,
        visible_only: Boolean(document.getElementById('chk-visible-only')?.checked)
    };

    state.isExtracting = true;
    toggleExtractionControls(true);
    setExtractionStatusBadge('running', 'Extracting...');
    showToast('Content extraction started.', 'info');

    try {
        const response = await api.startExtraction(config);
        if (response && response.success === false) {
            throw new Error(response.message || 'Failed to start content extraction');
        }
        const jobId = response.data?.job_id || response.job_id || response.id;

        if (!jobId) {
            throw new Error('No job ID was returned from server.');
        }

        state.extractionJobId = jobId;
        const jobIdEl = document.getElementById('extraction-job-id');
        if (jobIdEl) jobIdEl.textContent = jobId;

        // Reset previous extracted documents
        state.extractedDocuments = [];
        renderExtractionResults([]);

        // Disable export buttons until completion
        toggleExportButtons(false);

        // Start polling
        startPolling(jobId, 'extraction', 2000);

    } catch (error) {
        state.isExtracting = false;
        toggleExtractionControls(false);
        setExtractionStatusBadge('failed', 'Failed to start');
        showToast(error.message, 'error');
        showErrorModal('Error Starting Extraction', error.message);
    }
}

/**
 * Cancel the active extraction job
 */
async function cancelExtraction() {
    if (!state.extractionJobId || !state.isExtracting) return;

    try {
        showToast('Extraction stop request sent...', 'warning');
        await api.cancelExtraction(state.extractionJobId);
        stopPolling();
        state.isExtracting = false;
        toggleExtractionControls(false);
        setExtractionStatusBadge('cancelled', 'Stopped');
        showToast('Content extraction cancelled.', 'info');
    } catch (error) {
        showToast(error.message, 'error');
    }
}

/**
 * Retry failed documents in current extraction job
 */
async function retryFailedExtraction() {
    if (!state.extractionJobId) return;

    try {
        showToast('Retry request for failed items sent...', 'info');
        const res = await api.retryFailed(state.extractionJobId);
        if (res && res.success === false) {
            throw new Error(res.message || 'Failed to retry failed items');
        }
        const newJobId = res.data?.job_id || res.job_id || state.extractionJobId;
        state.extractionJobId = newJobId;
        const jobIdEl = document.getElementById('extraction-job-id');
        if (jobIdEl) jobIdEl.textContent = newJobId;

        state.isExtracting = true;
        toggleExtractionControls(true);
        setExtractionStatusBadge('running', 'Retrying failed items...');
        startPolling(newJobId, 'extraction', 2000);
    } catch (error) {
        showToast(error.message, 'error');
    }
}

/**
 * Update Extraction progress bar, stats, and results table
 * @param {Object} statusData 
 */
function updateExtractionProgress(statusData) {
    if (!statusData) return;

    const total = statusData.total ?? state.extractionUrls.size ?? 0;
    const completed = statusData.completed ?? 0;
    const failed = statusData.failed ?? 0;
    const jobStatus = (statusData.status || 'running').toLowerCase();

    // Update stats
    const totalEl = document.getElementById('stat-extraction-total');
    const compEl = document.getElementById('stat-extraction-completed');
    const failEl = document.getElementById('stat-extraction-failed');
    const wordsEl = document.getElementById('stat-extraction-words');

    if (totalEl) totalEl.textContent = total.toLocaleString('fa-IR');
    if (compEl) compEl.textContent = completed.toLocaleString('fa-IR');
    if (failEl) failEl.textContent = failed.toLocaleString('fa-IR');

    // Calculate total words
    const docs = statusData.documents || statusData.results || [];
    let totalWords = 0;
    if (Array.isArray(docs)) {
        totalWords = docs.reduce((acc, doc) => acc + (doc.word_count || 0), 0);
    }
    if (wordsEl) wordsEl.textContent = totalWords.toLocaleString('fa-IR');

    // Progress bar calculation
    let percent = 0;
    if (typeof statusData.progress === 'number') {
        percent = Math.min(100, Math.max(0, Math.round(statusData.progress)));
    } else if (total > 0) {
        percent = Math.min(100, Math.round(((completed + failed) / total) * 100));
    }

    const progressBar = document.getElementById('extraction-progress-bar');
    const progressText = document.getElementById('extraction-progress-text');
    if (progressBar) progressBar.style.width = `${percent}%`;
    if (progressText) progressText.textContent = `${percent}%`;

    // Render results
    if (Array.isArray(docs) && docs.length > 0) {
        state.extractedDocuments = docs;
        renderExtractionResults(docs);
    }

    // Toggle Retry button if failed items exist
    const btnRetry = document.getElementById('btn-retry-failed');
    if (btnRetry) {
        btnRetry.classList.toggle('hidden', failed === 0 || state.isExtracting);
    }

    // Check completion status
    if (['completed', 'finished', 'done', 'success'].includes(jobStatus)) {
        stopPolling();
        state.isExtracting = false;
        toggleExtractionControls(false);
        setExtractionStatusBadge('success', 'Extraction Completed');
        toggleExportButtons(true);
        if (progressBar) progressBar.style.width = '100%';
        if (progressText) progressText.textContent = '100%';
        showToast(`Extraction finished successfully. (${completed} succeeded, ${failed} failed)`, 'success');
    } else if (['failed', 'error'].includes(jobStatus)) {
        stopPolling();
        state.isExtracting = false;
        toggleExtractionControls(false);
        setExtractionStatusBadge('failed', 'Extraction Failed');
        toggleExportButtons(docs.length > 0);
        showToast(statusData.error || 'An error occurred during content extraction.', 'error');
    } else if (['cancelled', 'stopped'].includes(jobStatus)) {
        stopPolling();
        state.isExtracting = false;
        toggleExtractionControls(false);
        setExtractionStatusBadge('cancelled', 'Stopped');
        toggleExportButtons(docs.length > 0);
    } else {
        setExtractionStatusBadge('running', 'Processing...');
    }
}

/**
 * Render Extraction results table
 * @param {Array<Object>} docs 
 */
function renderExtractionResults(docs) {
    const tbody = document.getElementById('extraction-table-body');
    const showingCountEl = document.getElementById('extraction-showing-count');

    if (showingCountEl) showingCountEl.textContent = (docs || []).length.toLocaleString('fa-IR');
    if (!tbody) return;

    if (!docs || docs.length === 0) {
        tbody.innerHTML = `
            <tr class="empty-state-row">
                <td colspan="6">
                    <div class="empty-state">
                        <div class="empty-icon"><i class="fa-solid fa-newspaper"></i></div>
                        <h4>No pages extracted yet</h4>
                        <p>Add target URLs and click "Start Extraction".</p>
                    </div>
                </td>
            </tr>
        `;
        return;
    }

    let rowsHtml = '';
    docs.forEach((doc, idx) => {
        const url = doc.url || '';
        const title = doc.title || '(Untitled)';
        const docStatus = (doc.status || doc.quality_status || 'pending').toLowerCase();
        const wordCount = doc.word_count !== undefined ? doc.word_count.toLocaleString('fa-IR') : '0';

        // Engine and Page Type Badges
        const engine = (doc.extractor_used || doc.extraction_method || 'auto').toLowerCase();
        let engineBadge = `<span class="badge badge-secondary" style="font-size: 11px;"><i class="fa-solid fa-gear"></i> ${escapeHtml(engine)}</span>`;
        if (engine.includes('trafilatura')) {
            engineBadge = `<span class="badge badge-info" style="font-size: 11px;"><i class="fa-solid fa-feather"></i> Trafilatura</span>`;
        } else if (engine.includes('beautifulsoup') || engine.includes('bs4')) {
            engineBadge = `<span class="badge badge-warning" style="font-size: 11px;"><i class="fa-solid fa-code"></i> BS4</span>`;
        } else if (engine.includes('playwright') || engine.includes('playwrite')) {
            engineBadge = `<span class="badge badge-success" style="font-size: 11px;"><i class="fa-solid fa-masks-theater"></i> Playwright</span>`;
        } else if (engine.includes('crawl4ai')) {
            engineBadge = `<span class="badge badge-primary" style="font-size: 11px;"><i class="fa-solid fa-robot"></i> Crawl4AI</span>`;
        }

        const pageType = (doc.page_type || '').toLowerCase();
        const typeBadge = pageType && pageType !== 'unknown' 
            ? `<span class="badge badge-outline" style="font-size: 10px; margin-right: 4px;">${escapeHtml(pageType)}</span>` 
            : '';

        // Quality formatting from quality_report.score or doc.quality
        let qScore = null;
        if (doc.quality_report && typeof doc.quality_report.score === 'number') {
            qScore = doc.quality_report.score;
        } else if (typeof doc.quality === 'number') {
            qScore = Math.round(doc.quality <= 1.0 ? doc.quality * 100 : doc.quality);
        }

        let qualityTag = '<span class="quality-meter quality-medium">-</span>';
        if (qScore !== null) {
            if (qScore >= 70) qualityTag = `<span class="quality-meter quality-high">${qScore}/100</span>`;
            else if (qScore >= 40) qualityTag = `<span class="quality-meter quality-medium">${qScore}/100</span>`;
            else qualityTag = `<span class="quality-meter quality-low">${qScore}/100</span>`;
        }

        let badgeClass = 'badge-secondary';
        let statusLabel = docStatus;
        if (['success', 'completed', 'ok'].includes(docStatus)) {
            badgeClass = 'badge-success';
            statusLabel = t('status_extracted', 'Extracted');
        } else if (['failed', 'error'].includes(docStatus)) {
            badgeClass = 'badge-failed';
            statusLabel = t('status_error', 'Error');
        } else if (docStatus === 'empty') {
            badgeClass = 'badge-warning';
            statusLabel = t('status_empty_content', 'Empty Content');
        } else if (docStatus === 'low_quality') {
            badgeClass = 'badge-warning';
            statusLabel = t('status_low_quality', 'Low Quality');
        } else if (docStatus === 'blocked') {
            badgeClass = 'badge-failed';
            statusLabel = t('status_blocked_page', 'Blocked');
        } else if (docStatus === 'duplicate') {
            badgeClass = 'badge-secondary';
            statusLabel = t('status_duplicate', 'Duplicate');
        } else if (['running', 'in_progress', 'extracting'].includes(docStatus)) {
            badgeClass = 'badge-pending';
            statusLabel = t('status_in_progress', 'In Progress');
        } else {
            badgeClass = 'badge-secondary';
            statusLabel = docStatus || t('status_unknown', 'Unknown');
        }

        rowsHtml += `
            <tr>
                <td class="col-url" title="${escapeHtml(url)}">
                    <a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(url)}</a>
                </td>
                <td class="col-title" title="${escapeHtml(title)}">${escapeHtml(title)}</td>
                <td class="col-status">
                    <span class="badge ${badgeClass}">${escapeHtml(statusLabel)}</span>
                </td>
                <td class="col-engine">
                    ${engineBadge} ${typeBadge}
                </td>
                <td class="col-words">${wordCount}</td>
                <td class="col-quality">${qualityTag}</td>
                <td class="col-actions">
                    <button type="button" class="btn btn-outline btn-sm btn-preview-doc" data-idx="${idx}" title="View extracted content">
                        <i class="fa-solid fa-eye"></i>
                        <span>${t('view_btn', 'View')}</span>
                    </button>
                </td>
            </tr>
        `;
    });

    tbody.innerHTML = rowsHtml;

    // Attach click event for preview
    tbody.querySelectorAll('.btn-preview-doc').forEach(btn => {
        btn.addEventListener('click', () => {
            const docIndex = parseInt(btn.getAttribute('data-idx') || '0', 10);
            const doc = docs[docIndex];
            if (doc) openPreviewModal(doc);
        });
    });
}

/**
 * Toggle enable/disable extraction controls
 * @param {boolean} isRunning 
 */
function toggleExtractionControls(isRunning) {
    const btnStart = document.getElementById('btn-start-extraction');
    const btnCancel = document.getElementById('btn-cancel-extraction');
    const btnAddUrls = document.getElementById('btn-add-urls');
    const btnClearUrls = document.getElementById('btn-clear-selected-urls');

    if (btnStart) {
        btnStart.disabled = isRunning;
        btnStart.classList.toggle('hidden', isRunning);
    }
    if (btnCancel) {
        btnCancel.classList.toggle('hidden', !isRunning);
    }
    if (btnAddUrls) btnAddUrls.disabled = isRunning;
    if (btnClearUrls) btnClearUrls.disabled = isRunning;
}

/**
 * Set status badge text and style for extraction
 * @param {string} statusType 
 * @param {string} label 
 */
function setExtractionStatusBadge(statusType, label) {
    const badge = document.getElementById('extraction-status-badge');
    if (!badge) return;

    badge.className = 'badge';
    if (statusType === 'running') badge.classList.add('badge-pending');
    else if (statusType === 'success') badge.classList.add('badge-success');
    else if (statusType === 'failed') badge.classList.add('badge-failed');
    else if (statusType === 'cancelled') badge.classList.add('badge-blocked');
    else badge.classList.add('badge-secondary');

    badge.textContent = label;
}

/**
 * Toggle export buttons disabled state
 * @param {boolean} enabled 
 */
function toggleExportButtons(enabled) {
    document.querySelectorAll('.btn-export').forEach(btn => {
        btn.disabled = !enabled;
    });
}

// ============================================================================
// 7. Export Functions
// ============================================================================
/**
 * Export extracted documents in specified format (json, jsonl, markdown, text)
 * @param {string} format 
 */
async function exportResults(format) {
    if (!state.extractionJobId) {
        showToast('Extraction job ID not found.', 'warning');
        return;
    }

    try {
        showToast(`Generating and preparing ${format.toUpperCase()} export file...`, 'info');
        
        const dedup = Boolean(document.getElementById('chk-export-deduplicate')?.checked);
        let blob;
        try {
            // Attempt server-side export API
            blob = await api.exportDocuments(state.extractionJobId, format, dedup);
        } catch (apiError) {
            // Fallback to client-side generation if server export endpoint is unavailable
            console.warn('Server export endpoint failed, generating file locally...', apiError);
            blob = generateLocalExportBlob(state.extractedDocuments, format, dedup);
        }

        const extMap = {
            json: 'json',
            jsonl: 'jsonl',
            markdown: 'md',
            text: 'txt'
        };
        const fileExt = extMap[format] || format;
        const filename = `nexora_export_${state.extractionJobId.slice(0, 8)}_${new Date().toISOString().slice(0, 10)}.${fileExt}`;

        triggerBlobDownload(blob, filename);
        showToast(`Export file (${fileExt.toUpperCase()}) downloaded successfully.`, 'success');

    } catch (error) {
        showToast(`Export error: ${error.message}`, 'error');
    }
}

/**
 * Export discovered URLs from Discovery tab
 */
function exportDiscoveredUrls() {
    if (state.discoveredPages.length === 0) {
        showToast('No pages available to export.', 'warning');
        return;
    }

    // If items are selected, export selected; otherwise export all
    const urlsToExport = state.selectedUrls.size > 0
        ? Array.from(state.selectedUrls)
        : state.discoveredPages.map(p => p.url).filter(Boolean);

    const content = urlsToExport.join('\n');
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const filename = `discovered_urls_${new Date().toISOString().slice(0, 10)}.txt`;

    triggerBlobDownload(blob, filename);
    showToast(`${urlsToExport.length} URLs saved.`, 'success');
}

/**
 * Fallback client-side export generator
 * @param {Array<Object>} docs 
 * @param {string} format 
 * @param {boolean} deduplicate
 * @returns {Blob}
 */
function generateLocalExportBlob(docs, format, deduplicate = false) {
    let sourceDocs = docs || [];
    if (deduplicate) {
        const seenHashes = new Set();
        sourceDocs = sourceDocs.filter(d => {
            if (d.quality_status === 'duplicate' || d.quality_status?.value === 'duplicate') return false;
            const h = d.content_hash || d.source_doc_hash || (d.url + (d.content || d.text || ''));
            if (seenHashes.has(h)) return false;
            seenHashes.add(h);
            return true;
        });
    }

    let content = '';
    let mimeType = 'text/plain;charset=utf-8';

    if (format === 'json') {
        content = JSON.stringify(sourceDocs, null, 2);
        mimeType = 'application/json;charset=utf-8';
    } else if (format === 'jsonl') {
        content = sourceDocs.map(d => JSON.stringify(d)).join('\n');
        mimeType = 'application/x-ndjson;charset=utf-8';
    } else if (format === 'markdown') {
        content = sourceDocs.map(d => {
            return `# ${d.title || 'Untitled'}\n\n- **URL:** ${d.url}\n- **Date:** ${new Date().toISOString()}\n- **Words:** ${d.word_count || 0}\n\n---\n\n${d.content || d.text || ''}\n\n`;
        }).join('\n\n---\n\n');
        mimeType = 'text/markdown;charset=utf-8';
    } else { // text
        content = sourceDocs.map(d => {
            return `========================================\nURL: ${d.url}\nTITLE: ${d.title || ''}\n========================================\n\n${d.content || d.text || ''}\n\n`;
        }).join('\n\n');
        mimeType = 'text/plain;charset=utf-8';
    }

    return new Blob([content], { type: mimeType });
}

/**
 * Trigger file download via a created Blob URL
 * @param {Blob} blob 
 * @param {string} filename 
 */
function triggerBlobDownload(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }, 200);
}

// ============================================================================
// 8. Utility Functions
// ============================================================================
/**
 * Show a toast notification
 * @param {string} message 
 * @param {'success' | 'error' | 'warning' | 'info'} type 
 * @param {number} duration 
 */
function showToast(message, type = 'info', duration = 4000) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    let iconClass = 'fa-info-circle';
    if (type === 'success') iconClass = 'fa-circle-check';
    else if (type === 'error') iconClass = 'fa-triangle-exclamation';
    else if (type === 'warning') iconClass = 'fa-circle-exclamation';

    toast.innerHTML = `
        <i class="fa-solid ${iconClass} toast-icon"></i>
        <div class="toast-message">${escapeHtml(message)}</div>
    `;

    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('toast-hiding');
        setTimeout(() => {
            if (toast.parentElement) toast.parentElement.removeChild(toast);
        }, 260);
    }, duration);
}

/**
 * Show or hide full-page/element loading indicator
 * @param {boolean} show 
 */
function showLoading(show) {
    const indicator = document.getElementById('system-status-indicator');
    const text = document.getElementById('system-status-text');
    if (!indicator || !text) return;

    if (show) {
        indicator.classList.remove('active');
        text.innerHTML = '<span class="spinner"></span> ' + t('status_in_progress', 'In Progress...');
    } else {
        indicator.classList.add('active');
        text.textContent = t('sys_ready', 'System ready');
    }
}

/**
 * Truncate long URLs for display
 * @param {string} url 
 * @param {number} maxLength 
 * @returns {string}
 */
function formatUrl(url, maxLength = 50) {
    if (!url) return '';
    if (url.length <= maxLength) return url;
    return url.substring(0, maxLength - 3) + '...';
}

/**
 * Filter discovery results in real-time
 * @param {string} query 
 */
function filterResults(query) {
    state.searchQuery = (query || '').trim();
    const btnClear = document.getElementById('btn-clear-discovery-search');
    if (btnClear) {
        btnClear.classList.toggle('hidden', state.searchQuery === '');
    }

    const filtered = filterPages(state.discoveredPages, state.searchQuery);
    renderDiscoveryResults(filtered);
}

/**
 * Parse, clean, validate and deduplicate URLs from textarea
 * @param {string} text 
 * @returns {Array<string>}
 */
function parseUrlsFromTextarea(text) {
    if (!text) return [];

    const lines = text.split('\n');
    const validUrls = new Set();

    for (let line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;

        try {
            // Validate URL syntax
            const urlObj = new URL(trimmed);
            if (urlObj.protocol === 'http:' || urlObj.protocol === 'https:') {
                validUrls.add(trimmed);
            }
        } catch (_) {
            // Attempt prepend https:// if missing protocol
            if (trimmed.includes('.') && !trimmed.includes(' ')) {
                try {
                    const fallbackUrl = new URL('https://' + trimmed);
                    validUrls.add(fallbackUrl.href);
                } catch (__) {
                    // ignore invalid line
                }
            }
        }
    }

    return Array.from(validUrls);
}

/**
 * Open Preview Modal dialog for a document
 * @param {Object} doc 
 */
function openPreviewModal(doc) {
    const modal = document.getElementById('preview-modal');
    if (!modal) return;

    const urlEl = document.getElementById('modal-doc-url');
    const titleEl = document.getElementById('preview-modal-title');
    const statusEl = document.getElementById('modal-doc-status');
    const engineEl = document.getElementById('modal-doc-engine');
    const pageTypeEl = document.getElementById('modal-doc-page-type');
    const wordcountEl = document.getElementById('modal-doc-wordcount');
    const qualityEl = document.getElementById('modal-doc-quality');
    const contentEl = document.getElementById('modal-doc-content');

    if (urlEl) {
        urlEl.textContent = doc.url || '-';
        urlEl.href = doc.url || '#';
    }
    if (titleEl) titleEl.textContent = doc.title || t('modal_prev_title', 'Extracted Document Preview');
    if (statusEl) {
        const s = (doc.status || doc.quality_status || '').toLowerCase();
        let modalStatusLabel = t('status_extracted', 'Extracted');
        let modalBadgeClass = 'badge-success';
        if (['failed', 'error'].includes(s)) {
            modalBadgeClass = 'badge-failed';
            modalStatusLabel = t('status_error', 'Error');
        } else if (s === 'blocked') {
            modalBadgeClass = 'badge-failed';
            modalStatusLabel = t('status_blocked_page', 'Blocked');
        } else if (s === 'empty') {
            modalBadgeClass = 'badge-warning';
            modalStatusLabel = t('status_empty_content', 'Empty Content');
        } else if (s === 'low_quality') {
            modalBadgeClass = 'badge-warning';
            modalStatusLabel = t('status_low_quality', 'Low Quality');
        } else if (s === 'duplicate') {
            modalBadgeClass = 'badge-secondary';
            modalStatusLabel = t('status_duplicate', 'Duplicate');
        } else if (['running', 'in_progress'].includes(s)) {
            modalBadgeClass = 'badge-pending';
            modalStatusLabel = t('status_in_progress', 'In Progress');
        }
        statusEl.textContent = modalStatusLabel;
        statusEl.className = 'badge ' + modalBadgeClass;
    }
    if (engineEl) {
        engineEl.textContent = doc.extractor_used || doc.extraction_method || t('status_unknown', 'Unknown');
    }
    if (pageTypeEl) {
        pageTypeEl.textContent = doc.page_type || t('status_unknown', 'Unknown');
    }
    if (wordcountEl) wordcountEl.textContent = (doc.word_count || 0).toLocaleString(state.currentLang === 'fa' ? 'fa-IR' : 'en-US');

    let qDisplay = '-';
    if (doc.quality_report && typeof doc.quality_report.score === 'number') {
        qDisplay = `${doc.quality_report.score}/100`;
    } else if (doc.quality !== undefined) {
        qDisplay = typeof doc.quality === 'number' ? `${Math.round(doc.quality * 100)}%` : String(doc.quality);
    }
    if (qualityEl) qualityEl.textContent = qDisplay;

    if (contentEl) {
        const textToDisplay = doc.content_markdown || doc.content_text || doc.content || doc.text;
        if (textToDisplay && textToDisplay.trim()) {
            contentEl.textContent = textToDisplay;
        } else {
            const warningsList = (doc.warnings && doc.warnings.length > 0)
                ? '\n\n' + t('warnings_and_errors', 'Recorded Warnings & Errors:') + '\n' + doc.warnings.map(w => '• ' + w).join('\n')
                : '';
            contentEl.textContent = t('no_text_extracted', '⚠️ No text content could be extracted from this page.') + warningsList;
        }
    }

    modal.classList.remove('hidden');
    modal.setAttribute('aria-hidden', 'false');
}

/**
 * Close Preview Modal
 */
function closePreviewModal() {
    const modal = document.getElementById('preview-modal');
    if (modal) {
        modal.classList.add('hidden');
        modal.setAttribute('aria-hidden', 'true');
    }
}

/**
 * Show Error Details Modal
 * @param {string} title 
 * @param {string} message 
 * @param {string} [details] 
 */
function showErrorModal(title, message, details) {
    const modal = document.getElementById('error-modal');
    if (!modal) return;

    const titleEl = document.getElementById('error-modal-title');
    const msgEl = document.getElementById('error-modal-message');
    const detailsBox = document.getElementById('error-modal-details-box');
    const detailsCode = document.getElementById('error-modal-details');

    if (titleEl) titleEl.textContent = title;
    if (msgEl) msgEl.textContent = message;

    if (details && detailsBox && detailsCode) {
        detailsCode.textContent = typeof details === 'object' ? JSON.stringify(details, null, 2) : String(details);
        detailsBox.classList.remove('hidden');
    } else if (detailsBox) {
        detailsBox.classList.add('hidden');
    }

    modal.classList.remove('hidden');
    modal.setAttribute('aria-hidden', 'false');
}

/**
 * Close Error Modal
 */
function closeErrorModal() {
    const modal = document.getElementById('error-modal');
    if (modal) {
        modal.classList.add('hidden');
        modal.setAttribute('aria-hidden', 'true');
    }
}

/**
 * Basic HTML escaping utility
 * @param {string} str 
 * @returns {string}
 */
function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

// ============================================================================
// 9. Polling Engine
// ============================================================================
/**
 * Start recurring polling of job status
 * @param {string} jobId 
 * @param {'discovery' | 'extraction'} type 
 * @param {number} interval 
 */
function startPolling(jobId, type, interval = 2000) {
    stopPolling();

    state.activePollingType = type;
    showLoading(true);

    const pollTask = async () => {
        try {
            if (type === 'discovery') {
                const statusData = await api.getDiscoveryStatus(jobId);
                updateDiscoveryProgress(statusData);
            } else if (type === 'extraction') {
                const statusData = await api.getExtractionStatus(jobId);
                updateExtractionProgress(statusData);
            }
        } catch (error) {
            console.error(`Error polling ${type} job ${jobId}:`, error);
            showToast(`Status sync error: ${error.message}`, 'warning');
        }
    };

    // Immediate first tick
    pollTask();

    // Set recurring timer
    state.pollInterval = setInterval(pollTask, interval);
}

/**
 * Stop any active polling interval
 */
function stopPolling() {
    if (state.pollInterval) {
        clearInterval(state.pollInterval);
        state.pollInterval = null;
    }
    state.activePollingType = null;
    showLoading(false);
}

// ============================================================================
// 10. DOMContentLoaded & Event Listeners
// ============================================================================
document.addEventListener('DOMContentLoaded', () => {
    // ------------------------------------------------------------------------
    // Mobile Sidebar Drawer Toggle & Backdrop
    const btnToggleSidebar = document.getElementById('sidebar-toggle-btn');
    const appSidebar = document.getElementById('app-sidebar');
    const sidebarOverlay = document.getElementById('sidebar-overlay');
    if (btnToggleSidebar && appSidebar) {
        btnToggleSidebar.addEventListener('click', () => {
            const isOpen = appSidebar.classList.toggle('sidebar-open');
            if (sidebarOverlay) sidebarOverlay.classList.toggle('active', isOpen);
        });
    }
    if (sidebarOverlay && appSidebar) {
        sidebarOverlay.addEventListener('click', () => {
            appSidebar.classList.remove('sidebar-open');
            sidebarOverlay.classList.remove('active');
        });
    }

    // Tab switching buttons
    // ------------------------------------------------------------------------
    document.querySelectorAll('.tab-button').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const targetTab = btn.getAttribute('data-tab');
            if (targetTab) switchTab(targetTab);
        });
    });

    // ------------------------------------------------------------------------
    // Advanced settings panel toggle
    // ------------------------------------------------------------------------
    const btnToggleAdvanced = document.getElementById('btn-toggle-advanced');
    const advancedPanel = document.getElementById('discovery-advanced-panel');
    if (btnToggleAdvanced && advancedPanel) {
        btnToggleAdvanced.addEventListener('click', () => {
            const isOpen = advancedPanel.classList.toggle('open');
            btnToggleAdvanced.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
            advancedPanel.setAttribute('aria-hidden', isOpen ? 'false' : 'true');
        });
    }

    // ------------------------------------------------------------------------
    // Discovery action buttons
    // ------------------------------------------------------------------------
    const btnStartDiscovery = document.getElementById('btn-start-discovery');
    if (btnStartDiscovery) {
        btnStartDiscovery.addEventListener('click', startDiscovery);
    }

    const btnCancelDiscovery = document.getElementById('btn-cancel-discovery');
    if (btnCancelDiscovery) {
        btnCancelDiscovery.addEventListener('click', cancelDiscovery);
    }

    // Root URL Enter key shortcut
    const inputRootUrl = document.getElementById('input-root-url');
    if (inputRootUrl) {
        inputRootUrl.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                startDiscovery();
            }
        });
    }

    // ------------------------------------------------------------------------
    // Discovery table actions & search
    // ------------------------------------------------------------------------
    const searchInput = document.getElementById('input-discovery-search');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            filterResults(e.target.value);
        });
    }

    const btnClearSearch = document.getElementById('btn-clear-discovery-search');
    if (btnClearSearch && searchInput) {
        btnClearSearch.addEventListener('click', () => {
            searchInput.value = '';
            filterResults('');
            searchInput.focus();
        });
    }

    const btnSelectAll = document.getElementById('btn-select-all');
    if (btnSelectAll) {
        btnSelectAll.addEventListener('click', selectAll);
    }

    const btnDeselectAll = document.getElementById('btn-deselect-all');
    if (btnDeselectAll) {
        btnDeselectAll.addEventListener('click', deselectAll);
    }

    const headerCheckbox = document.getElementById('header-discovery-checkbox');
    if (headerCheckbox) {
        headerCheckbox.addEventListener('change', (e) => {
            if (e.target.checked) selectAll();
            else deselectAll();
        });
    }

    const btnSendToExtraction = document.getElementById('btn-send-to-extraction');
    if (btnSendToExtraction) {
        btnSendToExtraction.addEventListener('click', sendToExtraction);
    }

    const btnExportDiscovered = document.getElementById('btn-export-discovered-urls');
    if (btnExportDiscovered) {
        btnExportDiscovered.addEventListener('click', exportDiscoveredUrls);
    }

    // ------------------------------------------------------------------------
    // Extraction Tab Controls
    // ------------------------------------------------------------------------
    const btnAddUrls = document.getElementById('btn-add-urls');
    if (btnAddUrls) {
        btnAddUrls.addEventListener('click', addManualExtractionUrls);
    }

    const extractionTextarea = document.getElementById('input-extraction-urls-textarea');
    if (extractionTextarea) {
        extractionTextarea.addEventListener('input', (e) => {
            const count = parseUrlsFromTextarea(e.target.value).length;
            const badge = document.getElementById('urls-input-count');
            if (badge) badge.textContent = `${count} items`;
        });
    }

    const btnClearExtractionUrls = document.getElementById('btn-clear-selected-urls');
    if (btnClearExtractionUrls) {
        btnClearExtractionUrls.addEventListener('click', clearAllExtractionUrls);
    }

    const btnStartExtraction = document.getElementById('btn-start-extraction');
    if (btnStartExtraction) {
        btnStartExtraction.addEventListener('click', startExtraction);
    }

    const btnCancelExtraction = document.getElementById('btn-cancel-extraction');
    if (btnCancelExtraction) {
        btnCancelExtraction.addEventListener('click', cancelExtraction);
    }

    const btnRetryFailed = document.getElementById('btn-retry-failed');
    if (btnRetryFailed) {
        btnRetryFailed.addEventListener('click', retryFailedExtraction);
    }

    // Export formats buttons
    document.querySelectorAll('.btn-export').forEach(btn => {
        btn.addEventListener('click', () => {
            const format = btn.getAttribute('data-format');
            if (format) exportResults(format);
        });
    });

    // ------------------------------------------------------------------------
    // Modal dialog controls
    // ------------------------------------------------------------------------
    const btnClosePreview = document.getElementById('btn-close-preview-modal');
    const btnDismissPreview = document.getElementById('btn-dismiss-preview-modal');
    if (btnClosePreview) btnClosePreview.addEventListener('click', closePreviewModal);
    if (btnDismissPreview) btnDismissPreview.addEventListener('click', closePreviewModal);

    const btnCopyPreview = document.getElementById('btn-copy-preview-text');
    if (btnCopyPreview) {
        btnCopyPreview.addEventListener('click', () => {
            const contentEl = document.getElementById('modal-doc-content');
            if (contentEl && contentEl.textContent) {
                navigator.clipboard.writeText(contentEl.textContent)
                    .then(() => showToast('Document text copied to clipboard.', 'success'))
                    .catch(() => showToast('Failed to copy text.', 'error'));
            }
        });
    }

    const btnCloseError = document.getElementById('btn-close-error-modal');
    const btnDismissError = document.getElementById('btn-dismiss-error-modal');
    if (btnCloseError) btnCloseError.addEventListener('click', closeErrorModal);
    if (btnDismissError) btnDismissError.addEventListener('click', closeErrorModal);

    // Close modals on clicking overlay backdrop
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                closePreviewModal();
                closeErrorModal();
            }
        });
    });

    // Escape key closes open modals
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closePreviewModal();
            closeErrorModal();
        }
    });

    // Initial render
    renderDiscoveryResults([]);
    renderExtractionUrlList();
    renderExtractionResults([]);
    updateSelectedCounter();

    // ============================================================================
    // AI Features Module (LLM RAG · Text Chunking · Vector Embedding)
    // ============================================================================

    // ── AI State ──
    const aiState = {
        apiKeyConfigured: false,
        baseUrl: 'https://api.openai.com/v1',
        llmModel: 'gpt-4o-mini',
        embeddingModel: 'text-embedding-3-small',
        chunksReady: false,
        embeddingsReady: false,
        ragReady: false,
        currentJobId: null,
        lastEnhancedData: null,
        lastChunksData: null,
        activePreviewTab: 'json'
    };

    // ── AI API client methods ──
    const aiApi = {
        async getConfig() {
            const resp = await fetch('/api/ai/config', { headers: { Accept: 'application/json' } });
            if (!resp.ok) throw new Error('Failed to fetch AI configuration');
            return resp.json();
        },

        async saveConfig(data) {
            const resp = await fetch('/api/ai/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
                body: JSON.stringify(data)
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || err.message || 'Failed to save AI configuration');
            }
            return resp.json();
        },

        async testConnection(data) {
            const resp = await fetch('/api/ai/test-connection', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
                body: JSON.stringify(data)
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || err.message || 'Test connection request failed');
            }
            return resp.json();
        },

        async getStatus() {
            const resp = await fetch('/api/ai/status', { headers: { Accept: 'application/json' } });
            if (!resp.ok) throw new Error('Failed to fetch AI status');
            return resp.json();
        },

        async chunk(jobId, strategy, chunkSize, overlap, deduplicate = true) {
            const resp = await fetch('/api/ai/chunk', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
                body: JSON.stringify({
                    job_id: jobId,
                    strategy,
                    chunk_size: chunkSize,
                    overlap,
                    deduplicate_docs: deduplicate,
                    deduplicate_chunks: deduplicate,
                    normalize: true
                }),
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(data.detail || data.message || `Chunk error ${resp.status}`);
            return data;
        },

        async embed(jobId) {
            const resp = await fetch('/api/ai/embed', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
                body: JSON.stringify({ job_id: jobId }),
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(data.detail || data.message || `Embed error ${resp.status}`);
            return data;
        },

        async enhance(jobId) {
            const resp = await fetch('/api/ai/enhance', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
                body: JSON.stringify({ job_id: jobId }),
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(data.detail || data.message || `Enhance error ${resp.status}`);
            return data;
        },

        async exportAI(jobId, format) {
            const resp = await fetch('/api/ai/export', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ job_id: jobId, format }),
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || `Export error ${resp.status}`);
            }
            return resp.blob();
        },
    };

    // ── Helper: Set AI Pipeline Step State ──
    function setAIStep(stepId, stepState) {
        const icon = document.getElementById(`ai-step-${stepId}-icon`);
        const status = document.getElementById(`ai-step-${stepId}-status`);
        if (!icon) return;
        icon.className = `ai-step-icon ${stepState.cls}`;
        if (stepState.icon) icon.innerHTML = `<i class="${stepState.icon}"></i>`;
        if (status) status.textContent = stepState.text;
    }

    const AI_STEP_STATES = {
        pending:  (text) => ({ cls: 'pending', text: text || t('ai_step_pending', 'Pending...') }),
        running:  (text) => ({ cls: 'running', icon: 'fa-solid fa-spinner fa-spin', text: text || t('ai_step_running', 'Processing...') }),
        done:     (text) => ({ cls: 'done', icon: 'fa-solid fa-check', text: text || t('ai_step_done', 'Completed ✓') }),
        error:    (text) => ({ cls: 'error', icon: 'fa-solid fa-xmark', text: text || t('ai_step_error', 'Error') }),
        skipped:  (text) => ({ cls: 'skipped', icon: 'fa-solid fa-minus', text: text || t('ai_step_skipped', 'Skipped') }),
    };

    function showEl(id, visible) {
        const el = document.getElementById(id);
        if (!el) return;
        if (visible) el.classList.remove('hidden');
        else el.classList.add('hidden');
    }

    // ── Update Studio Info & Button States ──
    function updateAIStudioInfo() {
        const hasJob = !!state.extractionJobId;
        const docCount = state.extractedDocuments.length;

        // Update Job ID and Doc Count in Studio Header
        const jobIdEl = document.getElementById('ai-studio-job-id');
        const docCountEl = document.getElementById('ai-studio-doc-count');
        const tabAiBadge = document.getElementById('ai-badge-count');

        if (jobIdEl) jobIdEl.textContent = state.extractionJobId || t('no_job_active', 'No active job');
        const numLocale = state.currentLang === 'fa' ? 'fa-IR' : 'en-US';
        if (docCountEl) docCountEl.textContent = `${docCount.toLocaleString('en-US')} ${t('docs_extracted_suffix', 'documents extracted')}`;
        if (tabAiBadge) {
            tabAiBadge.textContent = docCount > 0 ? `${docCount} ${t('docs', 'docs')}` : 'AI';
        }

        // Master pipeline run button
        const btnRunAI = document.getElementById('btn-run-ai');
        if (btnRunAI) {
            const doChunk = document.getElementById('check-enable-chunking')?.checked;
            const doEmbed = document.getElementById('check-enable-embedding')?.checked;
            const doRAG = document.getElementById('check-enable-rag')?.checked;
            btnRunAI.disabled = !(hasJob && (doChunk || doEmbed || doRAG));
        }

        // Standalone Buttons
        const btnRunOnlyLLM = document.getElementById('btn-run-only-llm');
        if (btnRunOnlyLLM) {
            btnRunOnlyLLM.disabled = !(hasJob && aiState.apiKeyConfigured);
            btnRunOnlyLLM.title = !hasJob
                ? 'Extraction must be performed first'
                : (!aiState.apiKeyConfigured ? 'Requires NEXORA_OPENAI_API_KEY in .env file' : 'Run LLM Structure Enhancement');
        }

        const btnRunOnlyChunk = document.getElementById('btn-run-only-chunking');
        if (btnRunOnlyChunk) {
            btnRunOnlyChunk.disabled = !hasJob;
            btnRunOnlyChunk.title = !hasJob ? 'Extraction must be performed first' : 'Chunk extracted documents';
        }

        const btnRunOnlyEmbed = document.getElementById('btn-run-only-embedding');
        if (btnRunOnlyEmbed) {
            btnRunOnlyEmbed.disabled = !(hasJob && aiState.apiKeyConfigured);
            btnRunOnlyEmbed.title = !hasJob
                ? 'Extraction must be performed first'
                : (!aiState.apiKeyConfigured ? 'Requires NEXORA_OPENAI_API_KEY in .env file' : 'Generate Vector Embeddings');
        }
    }

    // ── Check AI Status on load & populate config ──
    async function checkAIStatus() {
        try {
            const resp = await aiApi.getStatus();
            const d = resp.data || {};
            aiState.apiKeyConfigured = d.api_key_configured || false;
            aiState.baseUrl = d.base_url || 'https://api.openai.com/v1';
            aiState.llmModel = d.llm_model || 'gpt-4o-mini';
            aiState.embeddingModel = d.embedding_model || 'text-embedding-3-small';

            showEl('ai-status-checking', false);
            if (aiState.apiKeyConfigured) {
                showEl('ai-status-ready', true);
                showEl('ai-status-no-key', false);
            } else {
                showEl('ai-status-ready', false);
                showEl('ai-status-no-key', true);
                const embedCheck = document.getElementById('check-enable-embedding');
                const ragCheck = document.getElementById('check-enable-rag');
                if (embedCheck) { embedCheck.disabled = true; embedCheck.title = 'Requires NEXORA_OPENAI_API_KEY'; }
                if (ragCheck) { ragCheck.disabled = true; ragCheck.title = 'Requires NEXORA_OPENAI_API_KEY'; }
            }

            // Populate labels in UI
            const baseUrlEl = document.getElementById('ai-status-base-url');
            if (baseUrlEl) baseUrlEl.textContent = aiState.baseUrl;

            const llmStatusEl = document.getElementById('ai-status-llm-model');
            if (llmStatusEl) llmStatusEl.textContent = aiState.llmModel;
            const cardLlmLabel = document.getElementById('card-llm-model-label');
            if (cardLlmLabel) cardLlmLabel.textContent = aiState.llmModel;

            const embedStatusEl = document.getElementById('ai-status-embed-model');
            if (embedStatusEl) embedStatusEl.textContent = aiState.embeddingModel;
            const cardEmbedLabel = document.getElementById('card-embed-model-label');
            if (cardEmbedLabel) cardEmbedLabel.textContent = aiState.embeddingModel;
            const badgeEmbedName = document.getElementById('badge-embed-model-name');
            if (badgeEmbedName) badgeEmbedName.textContent = aiState.embeddingModel;

        } catch (err) {
            console.error('Failed to check AI status:', err);
            showEl('ai-status-checking', false);
            showEl('ai-status-no-key', true);
        } finally {
            updateAIStudioInfo();
        }
    }

    // ── Live Preview Renderer ──
    function updateLivePreview(tab) {
        if (tab) aiState.activePreviewTab = tab;
        const codeEl = document.getElementById('ai-preview-code');
        const tagEl = document.getElementById('ai-preview-status-tag');
        const tabJson = document.getElementById('tab-preview-json');
        const tabChunks = document.getElementById('tab-preview-chunks');

        if (tabJson && tabChunks) {
            tabJson.classList.toggle('active', aiState.activePreviewTab === 'json');
            tabChunks.classList.toggle('active', aiState.activePreviewTab === 'chunks');
        }

        if (!codeEl) return;

        if (aiState.activePreviewTab === 'json') {
            if (aiState.lastEnhancedData) {
                codeEl.textContent = JSON.stringify(aiState.lastEnhancedData, null, 2);
                if (tagEl) tagEl.textContent = t('prev_tag_enhanced', 'Structured RAG Output Preview (Summaries, Keywords & Q&A)');
            } else if (state.extractedDocuments.length > 0) {
                const sample = state.extractedDocuments.slice(0, 2);
                codeEl.textContent = JSON.stringify({
                    info: t('toast_llm_first', 'Extracted documents are ready. Click "Run with LLM" to generate intelligent RAG structures.'),
                    sample_documents: sample
                }, null, 2);
                if (tagEl) tagEl.textContent = t('prev_tag_raw', 'Raw Documents Preview (Before LLM Enhancement)');
            } else {
                codeEl.textContent = t('prev_code_no_extract', '// No documents extracted yet. Please extract pages in the Extraction tab first.');
                if (tagEl) tagEl.textContent = t('prev_tag_waiting_extract', 'Awaiting Extraction');
            }
        } else { // 'chunks'
            if (aiState.lastChunksData) {
                const chunksList = Array.isArray(aiState.lastChunksData)
                    ? aiState.lastChunksData.slice(0, 5)
                    : (aiState.lastChunksData.chunks ? aiState.lastChunksData.chunks.slice(0, 5) : aiState.lastChunksData);
                codeEl.textContent = JSON.stringify(chunksList, null, 2);
                if (tagEl) tagEl.textContent = t('prev_tag_chunks', 'Sample of first 5 chunks ready for RAG');
            } else {
                codeEl.textContent = t('prev_code_no_chunks', '// Chunking has not been executed yet. Click "Run Chunking".');
                if (tagEl) tagEl.textContent = t('prev_tag_waiting_chunk', 'Awaiting Chunking');
            }
        }
    }

    // Preview Tab button clicks
    document.getElementById('tab-preview-json')?.addEventListener('click', () => updateLivePreview('json'));
    document.getElementById('tab-preview-chunks')?.addEventListener('click', () => updateLivePreview('chunks'));

    // Navigation Shortcuts
    document.getElementById('btn-goto-ai-tab')?.addEventListener('click', () => {
        switchTab('ai');
        checkAIStatus();
    });

    document.getElementById('btn-goto-ai-from-results')?.addEventListener('click', () => {
        switchTab('ai');
        checkAIStatus();
    });

    // ── AI Export Handler ──
    async function handleAIExport(format, filename) {
        const jobId = aiState.currentJobId || state.extractionJobId;
        if (!jobId) {
            showToast('Extraction job ID not found.', 'error');
            return;
        }
        try {
            showToast(`Preparing export file ${filename}...`, 'info');
            const blob = await aiApi.exportAI(jobId, format);
            triggerBlobDownload(blob, filename);
            showToast(`File ${filename} downloaded successfully.`, 'success');
        } catch (err) {
            showToast(`Download error: ${err.message}`, 'error');
        }
    }

    // Attach Export Buttons
    document.getElementById('btn-export-rag-json')?.addEventListener('click', () => {
        const jId = (aiState.currentJobId || state.extractionJobId || 'job').slice(0, 8);
        handleAIExport('json_enhanced', `rag_enhanced_${jId}.json`);
    });
    document.getElementById('btn-export-rag-jsonl')?.addEventListener('click', () => {
        const jId = (aiState.currentJobId || state.extractionJobId || 'job').slice(0, 8);
        handleAIExport('jsonl_enhanced', `rag_enhanced_${jId}.jsonl`);
    });
    document.getElementById('btn-export-rag-markdown')?.addEventListener('click', () => {
        const jId = (aiState.currentJobId || state.extractionJobId || 'job').slice(0, 8);
        handleAIExport('markdown_enhanced', `rag_markdown_${jId}.zip`);
    });
    document.getElementById('btn-export-chunks-jsonl')?.addEventListener('click', () => {
        const jId = (aiState.currentJobId || state.extractionJobId || 'job').slice(0, 8);
        handleAIExport('jsonl_chunks', `chunks_${jId}.jsonl`);
    });
    document.getElementById('btn-export-chunks-json')?.addEventListener('click', () => {
        const jId = (aiState.currentJobId || state.extractionJobId || 'job').slice(0, 8);
        handleAIExport('json_chunks', `chunks_${jId}.json`);
    });
    document.getElementById('btn-export-chunks-vectors')?.addEventListener('click', () => {
        const jId = (aiState.currentJobId || state.extractionJobId || 'job').slice(0, 8);
        handleAIExport('jsonl_chunks', `chunks_embedded_${jId}.jsonl`);
    });

    // ── Standalone Feature 1: LLM RAG Structuring ──
    const btnRunOnlyLLM = document.getElementById('btn-run-only-llm');
    if (btnRunOnlyLLM) {
        btnRunOnlyLLM.addEventListener('click', async () => {
            const jobId = state.extractionJobId;
            if (!jobId) {
                showToast('Extraction must be performed first.', 'error');
                return;
            }
            if (!aiState.apiKeyConfigured) {
                showToast('NEXORA_OPENAI_API_KEY is not set in .env.', 'warning');
                return;
            }

            const origContent = btnRunOnlyLLM.innerHTML;
            btnRunOnlyLLM.disabled = true;
            btnRunOnlyLLM.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> <span>Processing with LLM...</span>';
            showToast('Structured RAG processing with LLM started...', 'info');

            try {
                const res = await aiApi.enhance(jobId);
                aiState.currentJobId = jobId;
                aiState.ragReady = true;
                aiState.lastEnhancedData = res.data;

                const count = res.data?.enhanced_docs || state.extractedDocuments.length;
                document.getElementById('ai-stat-enhanced-value').textContent = count;
                showEl('ai-stats-panel', true);

                // Enable RAG export buttons
                document.getElementById('btn-export-rag-json').disabled = false;
                document.getElementById('btn-export-rag-jsonl').disabled = false;
                document.getElementById('btn-export-rag-markdown').disabled = false;

                // Update Preview to JSON tab
                updateLivePreview('json');
                showToast(`LLM processing completed: ${count} documents enriched with RAG structure.`, 'success');
            } catch (err) {
                showToast(`LLM processing error: ${err.message}`, 'error');
            } finally {
                btnRunOnlyLLM.disabled = false;
                btnRunOnlyLLM.innerHTML = origContent;
                updateAIStudioInfo();
            }
        });
    }

    // ── Standalone Feature 2: Text Chunking ──
    const btnRunOnlyChunking = document.getElementById('btn-run-only-chunking');
    if (btnRunOnlyChunking) {
        btnRunOnlyChunking.addEventListener('click', async () => {
            const jobId = state.extractionJobId;
            if (!jobId) {
                showToast('Extraction must be performed first.', 'error');
                return;
            }

            const strategy = document.getElementById('select-chunk-strategy')?.value || 'auto';
            const chunkSize = parseInt(document.getElementById('input-chunk-size')?.value || '1000', 10);
            const overlap = parseInt(document.getElementById('input-chunk-overlap')?.value || '150', 10);

            const origContent = btnRunOnlyChunking.innerHTML;
            btnRunOnlyChunking.disabled = true;
            btnRunOnlyChunking.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> <span>Chunking text...</span>';
            showToast('Text chunking started...', 'info');

            try {
                const dedup = Boolean(document.getElementById('chk-chunk-deduplicate')?.checked ?? true);
                const res = await aiApi.chunk(jobId, strategy, chunkSize, overlap, dedup);
                aiState.currentJobId = jobId;
                aiState.chunksReady = true;
                aiState.lastChunksData = res.data;

                const count = res.data?.total_chunks || 0;
                document.getElementById('ai-stat-chunks-value').textContent = count;
                showEl('ai-stats-panel', true);

                // Enable chunk export buttons
                document.getElementById('btn-export-chunks-jsonl').disabled = false;
                document.getElementById('btn-export-chunks-json').disabled = false;

                // Update Preview to chunks tab
                updateLivePreview('chunks');
                const stratName = res.data?.applied_strategy ? `${res.data.strategy} (${res.data.applied_strategy})` : (res.data?.strategy || strategy);
                showToast(`Chunking completed successfully: ${count} chunks created with ${stratName} strategy.`, 'success');
            } catch (err) {
                showToast(`Chunking error: ${err.message}`, 'error');
            } finally {
                btnRunOnlyChunking.disabled = false;
                btnRunOnlyChunking.innerHTML = origContent;
                updateAIStudioInfo();
            }
        });
    }

    // ── Standalone Feature 3: Vector Embedding ──
    const btnRunOnlyEmbedding = document.getElementById('btn-run-only-embedding');
    if (btnRunOnlyEmbedding) {
        btnRunOnlyEmbedding.addEventListener('click', async () => {
            const jobId = state.extractionJobId;
            if (!jobId) {
                showToast('Extraction must be performed first.', 'error');
                return;
            }
            if (!aiState.apiKeyConfigured) {
                showToast('NEXORA_OPENAI_API_KEY is not set in .env.', 'warning');
                return;
            }

            const origContent = btnRunOnlyEmbedding.innerHTML;
            btnRunOnlyEmbedding.disabled = true;
            btnRunOnlyEmbedding.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> <span>Generating embeddings...</span>';

            try {
                // If chunks haven't been generated yet, do chunking first automatically
                if (!aiState.chunksReady) {
                    showToast('Auto-chunking text first to generate chunks...', 'info');
                    const strategy = document.getElementById('select-chunk-strategy')?.value || 'auto';
                    const chunkSize = parseInt(document.getElementById('input-chunk-size')?.value || '1000', 10);
                    const overlap = parseInt(document.getElementById('input-chunk-overlap')?.value || '150', 10);
                    const dedup = Boolean(document.getElementById('chk-chunk-deduplicate')?.checked ?? true);
                    const chunkRes = await aiApi.chunk(jobId, strategy, chunkSize, overlap, dedup);
                    aiState.chunksReady = true;
                    aiState.lastChunksData = chunkRes.data;
                    document.getElementById('ai-stat-chunks-value').textContent = chunkRes.data?.total_chunks || 0;
                    document.getElementById('btn-export-chunks-jsonl').disabled = false;
                    document.getElementById('btn-export-chunks-json').disabled = false;
                }

                showToast(`Batch sending chunks to ${aiState.embeddingModel}...`, 'info');
                const embedRes = await aiApi.embed(jobId);
                aiState.currentJobId = jobId;
                aiState.embeddingsReady = true;

                const embeddedCount = embedRes.data?.embedded_chunks || 0;
                document.getElementById('ai-stat-embedded-value').textContent = embeddedCount;
                showEl('ai-stats-panel', true);

                // Enable vector export button
                document.getElementById('btn-export-chunks-vectors').disabled = false;

                // Update Preview
                updateLivePreview('chunks');
                showToast(`Vector generation completed successfully: ${embeddedCount} vectors (1536 dim) generated.`, 'success');
            } catch (err) {
                showToast(`Embedding generation error: ${err.message}`, 'error');
            } finally {
                btnRunOnlyEmbedding.disabled = false;
                btnRunOnlyEmbedding.innerHTML = origContent;
                updateAIStudioInfo();
            }
        });
    }

    // ── Master All-in-One Pipeline Execution ──
    const btnRunAI = document.getElementById('btn-run-ai');
    if (btnRunAI) {
        btnRunAI.addEventListener('click', async () => {
            const jobId = state.extractionJobId;
            if (!jobId) {
                showToast('Extraction must be performed first.', 'error');
                return;
            }

            const doChunk = document.getElementById('check-enable-chunking')?.checked;
            const doEmbed = document.getElementById('check-enable-embedding')?.checked;
            const doRAG = document.getElementById('check-enable-rag')?.checked;

            if (!doChunk && !doEmbed && !doRAG) {
                showToast('Select at least one AI capability.', 'warning');
                return;
            }

            showEl('ai-progress-section', true);
            btnRunAI.disabled = true;
            aiState.currentJobId = jobId;

            ['rag', 'chunking', 'embedding'].forEach(s => setAIStep(s, AI_STEP_STATES.pending()));

            let enhancedCount = 0;
            let chunkCount = 0;
            let embeddedCount = 0;

            // ─ Step 1: LLM RAG Structuring ─
            if (doRAG) {
                setAIStep('rag', AI_STEP_STATES.running('Processing structure with LLM...'));
                try {
                    const result = await aiApi.enhance(jobId);
                    enhancedCount = result.data?.enhanced_docs || state.extractedDocuments.length;
                    aiState.ragReady = true;
                    aiState.lastEnhancedData = result.data;
                    setAIStep('rag', AI_STEP_STATES.done(`${enhancedCount} documents enhanced ✓`));
                    document.getElementById('btn-export-rag-json').disabled = false;
                    document.getElementById('btn-export-rag-jsonl').disabled = false;
                    document.getElementById('btn-export-rag-markdown').disabled = false;
                } catch (err) {
                    setAIStep('rag', AI_STEP_STATES.error(err.message));
                    showToast(`RAG enhancement error: ${err.message}`, 'error');
                }
            } else {
                setAIStep('rag', AI_STEP_STATES.skipped('Not selected'));
            }

            // ─ Step 2: Chunking ─
            if (doChunk) {
                setAIStep('chunking', AI_STEP_STATES.running('Chunking text...'));
                try {
                    const strategy = document.getElementById('select-chunk-strategy')?.value || 'auto';
                    const chunkSize = parseInt(document.getElementById('input-chunk-size')?.value || '1000', 10);
                    const overlap = parseInt(document.getElementById('input-chunk-overlap')?.value || '150', 10);
                    const dedup = Boolean(document.getElementById('chk-chunk-deduplicate')?.checked ?? true);
                    const result = await aiApi.chunk(jobId, strategy, chunkSize, overlap, dedup);
                    chunkCount = result.data?.total_chunks || 0;
                    aiState.chunksReady = true;
                    aiState.lastChunksData = result.data;
                    const stratDesc = result.data?.applied_strategy ? ` [${result.data.applied_strategy}]` : '';
                    setAIStep('chunking', AI_STEP_STATES.done(`${chunkCount} chunks generated${stratDesc} ✓`));
                    document.getElementById('btn-export-chunks-jsonl').disabled = false;
                    document.getElementById('btn-export-chunks-json').disabled = false;
                } catch (err) {
                    setAIStep('chunking', AI_STEP_STATES.error(err.message));
                    showToast(`Chunking error: ${err.message}`, 'error');
                }
            } else {
                setAIStep('chunking', AI_STEP_STATES.skipped('Not selected'));
            }

            // ─ Step 3: Embedding ─
            if (doEmbed) {
                if (!aiState.chunksReady && !doChunk) {
                    setAIStep('embedding', AI_STEP_STATES.error('Enable chunking first'));
                    showToast('Chunking is required before vector embedding.', 'warning');
                } else {
                    setAIStep('embedding', AI_STEP_STATES.running('Generating embeddings...'));
                    try {
                        const result = await aiApi.embed(jobId);
                        embeddedCount = result.data?.embedded_chunks || 0;
                        aiState.embeddingsReady = true;
                        setAIStep('embedding', AI_STEP_STATES.done(`${embeddedCount} vectors generated ✓`));
                        document.getElementById('btn-export-chunks-vectors').disabled = false;
                    } catch (err) {
                        setAIStep('embedding', AI_STEP_STATES.error(err.message));
                        showToast(`Embedding error: ${err.message}`, 'error');
                    }
                }
            } else {
                setAIStep('embedding', AI_STEP_STATES.skipped('Not selected'));
            }

            // Show Stats
            showEl('ai-stats-panel', true);
            document.getElementById('ai-stat-enhanced-value').textContent = doRAG ? enhancedCount : '—';
            document.getElementById('ai-stat-chunks-value').textContent = doChunk ? chunkCount : '—';
            document.getElementById('ai-stat-embedded-value').textContent = doEmbed ? embeddedCount : '—';

            // Update live preview
            updateLivePreview(doRAG ? 'json' : (doChunk ? 'chunks' : 'json'));

            btnRunAI.disabled = false;
            updateAIStudioInfo();
            showToast('AI pipeline process completed.', 'success');
        });
    }

    // Checkbox changes re-evaluate master run button
    ['check-enable-chunking', 'check-enable-embedding', 'check-enable-rag'].forEach(id => {
        document.getElementById(id)?.addEventListener('change', updateAIStudioInfo);
    });

    // ------------------------------------------------------------------------
    // Module: File & Data Processing Studio
    // ------------------------------------------------------------------------
    const fileState = {
        uploadedFileId: null,
        uploadedFileInfo: null,
        lastArtifactData: null,
        activePreviewTab: 'output',
    };

    const filesApi = {
        async upload(file) {
            const formData = new FormData();
            formData.append('file', file);
            const res = await fetch('/api/files/upload', {
                method: 'POST',
                body: formData,
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || 'File upload error');
            }
            return res.json();
        },
        async process(fileId, operations, options) {
            const res = await fetch('/api/files/process', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ file_id: fileId, operations, options }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || 'File processing error');
            }
            return res.json();
        },
    };

    function initFileProcessingStudio() {
        const dropzone = document.getElementById('file-dropzone');
        const fileInput = document.getElementById('input-file-upload');
        const btnRunProcess = document.getElementById('btn-run-file-process');
        const fileInfoPanel = document.getElementById('file-info-panel');
        const fileResultsPanel = document.getElementById('file-results-panel');

        if (!dropzone || !fileInput) return;

        dropzone.addEventListener('click', () => fileInput.click());

        ['dragenter', 'dragover'].forEach(eventName => {
            dropzone.addEventListener(eventName, (e) => {
                e.preventDefault();
                dropzone.classList.add('dragover');
            });
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropzone.addEventListener(eventName, (e) => {
                e.preventDefault();
                dropzone.classList.remove('dragover');
            });
        });

        dropzone.addEventListener('drop', (e) => {
            const files = e.dataTransfer?.files;
            if (files && files.length > 0) {
                handleFileSelect(files[0]);
            }
        });

        fileInput.addEventListener('change', () => {
            if (fileInput.files && fileInput.files.length > 0) {
                handleFileSelect(fileInput.files[0]);
            }
        });

        async function handleFileSelect(file) {
            showToast(t('toast_file_uploading', 'Uploading file...') + ` (${file.name})`, 'info');
            try {
                const res = await filesApi.upload(file);
                const info = res.data;
                fileState.uploadedFileId = info.file_id;
                fileState.uploadedFileInfo = info;

                document.getElementById('file-info-name').textContent = info.filename;
                document.getElementById('file-info-format').textContent = (info.format || '').toUpperCase();
                document.getElementById('file-info-size').textContent = `${(info.size_bytes / 1024).toFixed(1)} KB`;
                document.getElementById('file-info-lines').textContent = info.line_count || '0';
                document.getElementById('file-info-encoding').textContent = info.encoding || 'UTF-8';

                showEl('file-info-panel', true);
                if (btnRunProcess) btnRunProcess.disabled = false;
                const badge = document.getElementById('files-badge-count');
                if (badge) badge.textContent = '1';

                showToast(`${info.filename} ` + t('toast_file_upload_success', 'uploaded successfully.'), 'success');
            } catch (err) {
                showToast(`File upload error: ${err.message}`, 'error');
            }
        }

        if (btnRunProcess) {
            btnRunProcess.addEventListener('click', async () => {
                if (!fileState.uploadedFileId) {
                    showToast('Please upload a valid file first.', 'warning');
                    return;
                }

                const ops = [];
                if (document.getElementById('check-file-op-normalize')?.checked) ops.push('normalize');
                if (document.getElementById('check-file-op-dedup')?.checked) ops.push('deduplicate');
                if (document.getElementById('check-file-op-chunk')?.checked) ops.push('chunk');
                if (document.getElementById('check-file-op-ai')?.checked) ops.push('llm_json_optimize');
                if (document.getElementById('check-file-op-embed')?.checked) ops.push('embed');
                if (document.getElementById('check-file-op-md2json')?.checked) ops.push('markdown_to_json');
                if (document.getElementById('check-file-op-validate')?.checked) ops.push('json_validate');
                if (document.getElementById('check-file-op-cleanup')?.checked) ops.push('json_cleanup');
                if (document.getElementById('check-file-op-enrich')?.checked) ops.push('metadata_enrich');

                if (ops.length === 0) {
                    showToast('Select at least one processing operation.', 'warning');
                    return;
                }

                const options = {
                    chunk_strategy: document.getElementById('select-file-chunk-strategy')?.value || 'auto',
                    chunk_size: parseInt(document.getElementById('input-file-chunk-size')?.value || '1000', 10),
                    overlap: parseInt(document.getElementById('input-file-chunk-overlap')?.value || '150', 10),
                    category: document.getElementById('input-file-category')?.value || null,
                    output_format: document.getElementById('select-file-output-format')?.value || 'json',
                    deduplicate_chunks: Boolean(document.getElementById('check-file-op-dedup')?.checked),
                };

                const origHtml = btnRunProcess.innerHTML;
                btnRunProcess.disabled = true;
                btnRunProcess.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> <span>' + t('fp_processing', 'Processing pipeline...') + '</span>';
                showToast('Pipeline processing started...', 'info');

                try {
                    const res = await filesApi.process(fileState.uploadedFileId, ops, options);
                    const data = res.data;
                    fileState.lastArtifactData = data;

                    document.getElementById('stat-file-records-in').textContent = data.telemetry?.records_in || 0;
                    document.getElementById('stat-file-records-out').textContent = data.telemetry?.records_out || 0;
                    document.getElementById('stat-file-chunks').textContent = data.telemetry?.chunks_produced || 0;
                    const statVectors = document.getElementById('stat-file-vectors');
                    if (statVectors) statVectors.textContent = data.telemetry?.embedded_chunks || 0;
                    document.getElementById('stat-file-fixes').textContent = data.telemetry?.normalization_fixes || 0;
                    document.getElementById('stat-file-duration').textContent = `${data.duration_seconds || 0}s`;

                    if (data.telemetry?.warnings && data.telemetry.warnings.length > 0) {
                        showToast(data.telemetry.warnings[0], 'warning');
                    }

                    const btnDownload = document.getElementById('btn-download-file-result');
                    if (btnDownload) {
                        btnDownload.href = data.download_url;
                        btnDownload.setAttribute('download', data.filename);
                    }

                    const preOutput = document.getElementById('file-preview-output-content');
                    if (preOutput) preOutput.textContent = data.output_preview || t('fp_output_empty', '// Output empty');

                    const preDiff = document.getElementById('file-preview-diff-content');
                    if (preDiff) preDiff.textContent = data.diff || t('fp_diff_empty', '// No changes from original version.');

                    showEl('file-results-panel', true);
                    const dedupMsg = data.telemetry?.duplicates_removed ? ` (${data.telemetry.duplicates_removed} duplicates removed)` : '';
                    showToast(t('toast_file_proc_success', 'File pipeline processing completed successfully.') + dedupMsg, 'success');
                } catch (err) {
                    showToast(`File processing error: ${err.message}`, 'error');
                } finally {
                    btnRunProcess.disabled = false;
                    btnRunProcess.innerHTML = origHtml;
                }
            });
        }

        const tabOutput = document.getElementById('tab-file-preview-output');
        const tabDiff = document.getElementById('tab-file-preview-diff');
        const codeOutput = document.getElementById('file-preview-output-content');
        const codeDiff = document.getElementById('file-preview-diff-content');

        if (tabOutput && tabDiff) {
            tabOutput.addEventListener('click', () => {
                tabOutput.classList.add('active');
                tabDiff.classList.remove('active');
                if (codeOutput) codeOutput.classList.remove('hidden');
                if (codeDiff) codeDiff.classList.add('hidden');
            });
            tabDiff.addEventListener('click', () => {
                tabDiff.classList.add('active');
                tabOutput.classList.remove('active');
                if (codeOutput) codeOutput.classList.add('hidden');
                if (codeDiff) codeDiff.classList.remove('hidden');
            });
        }
    }

    // Language switcher segmented buttons
    const btnFa = document.getElementById('lang-btn-fa');
    if (btnFa) {
        btnFa.addEventListener('click', (e) => {
            e.preventDefault();
            setLanguage('fa');
        });
    }

    const btnEn = document.getElementById('lang-btn-en');
    if (btnEn) {
        btnEn.addEventListener('click', (e) => {
            e.preventDefault();
            setLanguage('en');
        });
    }

    const btnToggleLang = document.getElementById('btn-toggle-lang');
    if (btnToggleLang) {
        btnToggleLang.addEventListener('click', (e) => {
            e.preventDefault();
            const nextLang = (state.currentLang === 'fa') ? 'en' : 'fa';
            setLanguage(nextLang);
        });
    }

    // Apply saved or default language
    setLanguage(state.currentLang);

    // Initial check on load
    checkAIStatus();
    updateLivePreview('json');
    initFileProcessingStudio();
    initDataStudio();
    initEvalStudio();
    initAISettingsModal();

    // ── AI Provider & Model Settings Modal Controller ──
    function initAISettingsModal() {
        const modal = document.getElementById('ai-settings-modal');
        if (!modal) return;

        const alertBox = document.getElementById('ai-settings-alert');
        const presetSelect = document.getElementById('ai-preset-select');
        const inputApiKey = document.getElementById('ai-input-api-key');
        const btnToggleKeyVis = document.getElementById('btn-toggle-key-visibility');
        const iconKeyVis = document.getElementById('icon-key-visibility');
        const keyBadge = document.getElementById('ai-key-status-badge');
        const inputBaseUrl = document.getElementById('ai-input-base-url');
        const selectLLM = document.getElementById('ai-select-llm-model');
        const inputCustomLLM = document.getElementById('ai-input-custom-llm');
        const selectEmbed = document.getElementById('ai-select-embed-model');
        const inputCustomEmbed = document.getElementById('ai-input-custom-embed');
        const btnTest = document.getElementById('btn-test-ai-connection');
        const btnSave = document.getElementById('btn-save-ai-settings');
        const btnCloseX = document.getElementById('btn-close-ai-settings-x');
        const btnDismiss = document.getElementById('btn-dismiss-ai-settings-modal');

        const presets = {
            openai: {
                baseUrl: '',
                llm: 'gpt-4o-mini',
                embed: 'text-embedding-3-small'
            },
            avalai: {
                baseUrl: 'https://api.avalai.ir/v1',
                llm: 'gpt-6-luna',
                embed: 'text-embedding-3-small'
            },
            openrouter: {
                baseUrl: 'https://openrouter.ai/api/v1',
                llm: 'gpt-4o-mini',
                embed: 'text-embedding-3-small'
            },
            deepseek: {
                baseUrl: 'https://api.deepseek.com/v1',
                llm: 'deepseek-chat',
                embed: 'text-embedding-3-small'
            },
            groq: {
                baseUrl: 'https://api.groq.com/openai/v1',
                llm: 'llama-3.3-70b-versatile',
                embed: 'text-embedding-3-small'
            },
            ollama: {
                baseUrl: 'http://localhost:11434/v1',
                llm: 'llama3',
                embed: 'bge-m3'
            }
        };

        function setSelectOrCustom(selectEl, customInputEl, value) {
            if (!selectEl) return;
            let found = false;
            for (let i = 0; i < selectEl.options.length; i++) {
                if (selectEl.options[i].value === value) {
                    selectEl.selectedIndex = i;
                    found = true;
                    break;
                }
            }
            if (!found && value) {
                selectEl.value = '__custom__';
                if (customInputEl) {
                    customInputEl.value = value;
                    customInputEl.classList.remove('hidden');
                }
            } else {
                if (customInputEl) customInputEl.classList.add('hidden');
            }
        }

        function getSelectedModel(selectEl, customInputEl) {
            if (selectEl && selectEl.value === '__custom__') {
                return (customInputEl ? customInputEl.value : '').trim();
            }
            return selectEl ? selectEl.value : '';
        }

        function closeModal() {
            modal.classList.add('hidden');
            if (inputApiKey) inputApiKey.type = 'password';
            if (iconKeyVis) iconKeyVis.className = 'fa-solid fa-eye';
            if (alertBox) {
                alertBox.className = 'alert hidden';
                alertBox.textContent = '';
                alertBox.removeAttribute('style');
            }
        }

        async function openModal() {
            modal.classList.remove('hidden');
            if (alertBox) {
                alertBox.className = 'alert hidden';
                alertBox.textContent = '';
                alertBox.removeAttribute('style');
            }

            try {
                const cfg = await aiApi.getConfig();
                if (inputApiKey) {
                    inputApiKey.value = cfg.raw_api_key || '';
                }
                if (inputBaseUrl) {
                    inputBaseUrl.value = cfg.base_url || '';
                }

                if (keyBadge) {
                    if (cfg.api_key_configured) {
                        keyBadge.textContent = 'Configured (' + (cfg.masked_api_key || 'Active') + ')';
                        keyBadge.style.background = 'rgba(16, 185, 129, 0.15)';
                        keyBadge.style.color = '#10b981';
                    } else {
                        keyBadge.textContent = 'Not configured';
                        keyBadge.style.background = 'rgba(239, 68, 68, 0.15)';
                        keyBadge.style.color = '#ef4444';
                    }
                }

                if (selectLLM && inputCustomLLM) {
                    setSelectOrCustom(selectLLM, inputCustomLLM, cfg.llm_model || 'gpt-4o-mini');
                }
                if (selectEmbed && inputCustomEmbed) {
                    setSelectOrCustom(selectEmbed, inputCustomEmbed, cfg.embedding_model || 'text-embedding-3-small');
                }

                // Detect matching preset
                if (presetSelect) {
                    const rawBase = (cfg.base_url || '').trim().replace(/\/+$/, '');
                    let matched = 'custom';
                    for (const [k, p] of Object.entries(presets)) {
                        if (p.baseUrl && p.baseUrl.replace(/\/+$/, '') === rawBase) {
                            matched = k;
                            break;
                        }
                    }
                    if (!rawBase) {
                        matched = 'openai';
                    }
                    presetSelect.value = matched;
                }
            } catch (err) {
                console.error('Failed to load AI config in modal:', err);
            }
        }

        // Preset Change
        if (presetSelect) {
            presetSelect.addEventListener('change', () => {
                const choice = presetSelect.value;
                if (choice === 'custom') return;
                const p = presets[choice];
                if (p) {
                    if (inputBaseUrl) inputBaseUrl.value = p.baseUrl;
                    if (selectLLM && inputCustomLLM) {
                        setSelectOrCustom(selectLLM, inputCustomLLM, p.llm);
                    }
                    if (selectEmbed && inputCustomEmbed) {
                        setSelectOrCustom(selectEmbed, inputCustomEmbed, p.embed);
                    }
                }
            });
        }

        // Custom toggles
        if (selectLLM && inputCustomLLM) {
            selectLLM.addEventListener('change', () => {
                if (selectLLM.value === '__custom__') {
                    inputCustomLLM.classList.remove('hidden');
                    inputCustomLLM.focus();
                } else {
                    inputCustomLLM.classList.add('hidden');
                }
            });
        }

        if (selectEmbed && inputCustomEmbed) {
            selectEmbed.addEventListener('change', () => {
                if (selectEmbed.value === '__custom__') {
                    inputCustomEmbed.classList.remove('hidden');
                    inputCustomEmbed.focus();
                } else {
                    inputCustomEmbed.classList.add('hidden');
                }
            });
        }

        // Toggle Key Visibility
        if (btnToggleKeyVis && inputApiKey && iconKeyVis) {
            btnToggleKeyVis.addEventListener('click', () => {
                if (inputApiKey.type === 'password') {
                    inputApiKey.type = 'text';
                    iconKeyVis.className = 'fa-solid fa-eye-slash';
                } else {
                    inputApiKey.type = 'password';
                    iconKeyVis.className = 'fa-solid fa-eye';
                }
            });
        }

        // Test Connection
        if (btnTest) {
            btnTest.addEventListener('click', async () => {
                const keyVal = inputApiKey ? inputApiKey.value.trim() : '';
                const baseVal = inputBaseUrl ? inputBaseUrl.value.trim() : '';
                const llmVal = (selectLLM && inputCustomLLM) ? getSelectedModel(selectLLM, inputCustomLLM) : 'gpt-4o-mini';
                const embedVal = (selectEmbed && inputCustomEmbed) ? getSelectedModel(selectEmbed, inputCustomEmbed) : 'text-embedding-3-small';

                const origHtml = btnTest.innerHTML;
                btnTest.disabled = true;
                btnTest.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> <span>Testing...</span>';
                if (alertBox) {
                    alertBox.className = 'alert hidden';
                    alertBox.textContent = '';
                    alertBox.removeAttribute('style');
                }

                try {
                    const res = await aiApi.testConnection({
                        api_key: keyVal,
                        base_url: baseVal,
                        llm_model: llmVal,
                        embedding_model: embedVal
                    });
                    if (alertBox) {
                        alertBox.className = 'alert alert-success';
                        alertBox.style.cssText = 'margin-bottom: 1.25rem; padding: 0.75rem 1rem; border-radius: 6px; font-size: 0.88rem; background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.3);';
                        alertBox.innerHTML = '<i class="fa-solid fa-circle-check"></i> ' + (res.message || 'Connection successful!') + ' <span style="font-size:0.8rem; opacity:0.85;">(' + res.latency_ms + 'ms)</span>';
                    }
                } catch (err) {
                    if (alertBox) {
                        alertBox.className = 'alert alert-danger';
                        alertBox.style.cssText = 'margin-bottom: 1.25rem; padding: 0.75rem 1rem; border-radius: 6px; font-size: 0.88rem; background: rgba(239, 68, 68, 0.15); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.3);';
                        alertBox.innerHTML = '<i class="fa-solid fa-triangle-exclamation"></i> ' + (err.message || 'Connection failed.');
                    }
                } finally {
                    btnTest.disabled = false;
                    btnTest.innerHTML = origHtml;
                }
            });
        }

        // Save Settings
        if (btnSave) {
            btnSave.addEventListener('click', async () => {
                const keyVal = inputApiKey ? inputApiKey.value.trim() : '';
                const baseVal = inputBaseUrl ? inputBaseUrl.value.trim() : '';
                const llmVal = (selectLLM && inputCustomLLM) ? getSelectedModel(selectLLM, inputCustomLLM) : 'gpt-4o-mini';
                const embedVal = (selectEmbed && inputCustomEmbed) ? getSelectedModel(selectEmbed, inputCustomEmbed) : 'text-embedding-3-small';

                const origHtml = btnSave.innerHTML;
                btnSave.disabled = true;
                btnSave.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> <span>Saving...</span>';

                try {
                    const res = await aiApi.saveConfig({
                        api_key: keyVal,
                        base_url: baseVal,
                        llm_model: llmVal,
                        embedding_model: embedVal
                    });
                    showToast(res.message || 'AI configuration saved to .env and applied to live runtime!', 'success');
                    closeModal();
                    await checkAIStatus();
                } catch (err) {
                    if (alertBox) {
                        alertBox.className = 'alert alert-danger';
                        alertBox.style.cssText = 'margin-bottom: 1.25rem; padding: 0.75rem 1rem; border-radius: 6px; font-size: 0.88rem; background: rgba(239, 68, 68, 0.15); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.3);';
                        alertBox.innerHTML = '<i class="fa-solid fa-triangle-exclamation"></i> ' + (err.message || 'Failed to save configuration.');
                    }
                } finally {
                    btnSave.disabled = false;
                    btnSave.innerHTML = origHtml;
                }
            });
        }

        // Open triggers
        document.getElementById('btn-open-ai-settings')?.addEventListener('click', openModal);
        document.getElementById('btn-quick-ai-settings')?.addEventListener('click', openModal);
        document.getElementById('btn-edit-ai-config')?.addEventListener('click', openModal);

        // Close triggers
        btnCloseX?.addEventListener('click', closeModal);
        btnDismiss?.addEventListener('click', closeModal);
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeModal();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !modal.classList.contains('hidden')) {
                closeModal();
            }
        });
    }

    // Periodic synchronization with active extraction job
    setInterval(() => {
        updateAIStudioInfo();
    }, 1500);

});

    // =========================================================================
    // Phase 2: Professional Data Studio (Stages, Chunks, Quality, Versions)
    // =========================================================================

    function initDataStudio() {
        let currentChunkPage = 1;
        let selectedChunkForEdit = null;

        function getActiveJobId() {
            if (state.extractionJobId) return state.extractionJobId;
            if (state.discoveryJobId) return state.discoveryJobId;
            const domText = document.getElementById('ai-studio-job-id')?.textContent.trim();
            // Only accept if it looks like a valid UUID/job identifier, never placeholder text
            if (domText && /^[0-9a-fA-F-]{8,}$/.test(domText)) {
                return domText;
            }
            return null;
        }

        function requireJobId() {
            const jid = getActiveJobId();
            if (!jid) {
                showToast('Please perform an extraction or chunking operation first to select an active job.', 'warning');
                return null;
            }
            return jid;
        }

        // --- 1. Stage Inspector ---
        const btnOpenStages = document.getElementById('btn-open-stages-modal');
        const modalStages = document.getElementById('stages-modal');
        const btnCloseStages = document.getElementById('btn-close-stages-modal');
        const btnDismissStages = document.getElementById('btn-dismiss-stages-modal');
        const btnRefreshStages = document.getElementById('btn-refresh-stages');

        async function loadStages() {
            const jid = requireJobId();
            if (!jid) return;
            const container = document.getElementById('stages-timeline-list');
            if (container) {
                container.innerHTML = '<div class="empty-state"><i class="fa-solid fa-spinner fa-spin"></i> Loading pipeline stages...</div>';
            }
            if (modalStages) modalStages.classList.remove('hidden');

            try {
                const resp = await fetch(`/api/ai/stages/${jid}`);
                const res = await resp.json();
                if (!resp.ok) throw new Error(res.detail || 'Error fetching stages');
                renderStages(res.data.stages, container);
            } catch (err) {
                if (container) container.innerHTML = `<div class="empty-state text-danger">${err.message}</div>`;
            }
        }

        function renderStages(stages, container) {
            if (!stages || stages.length === 0) {
                container.innerHTML = '<div class="empty-state">No stages found to display.</div>';
                return;
            }
            let html = '';
            stages.forEach((st, idx) => {
                const activeClass = st.available ? 'stage-active' : '';
                const pillText = st.available ? 'Completed' : 'Pending / Disabled';
                html += `
                    <div class="stage-step-card ${activeClass}">
                        <div class="stage-header-row">
                            <span class="stage-title">
                                <span style="color: var(--color-primary); font-family: monospace;">#${idx + 1}</span>
                                ${st.stage_name}
                            </span>
                            <span class="stage-pill">${pillText}</span>
                        </div>
                        <div class="stage-desc">${st.input_description}</div>
                        <div class="stage-meta-row">
                            <span><i class="fa-solid fa-calculator text-primary"></i> Count: <strong>${st.item_count}</strong></span>
                            <span><i class="fa-solid fa-font text-primary"></i> Characters: <strong>${st.char_count}</strong></span>
                            <span><i class="fa-solid fa-gears text-primary"></i> Operations: <strong>${(st.operations_applied || []).join(', ')}</strong></span>
                        </div>
                        ${st.preview ? `<div class="stage-preview-box">${escapeHtml(st.preview)}</div>` : ''}
                        ${st.diff_with_previous ? `
                            <div style="margin-top: 0.5rem;">
                                <label style="font-size: 0.75rem; color: var(--color-text-muted);">Changes vs previous stage (Diff):</label>
                                <div class="stage-preview-box" style="color: #3CAEC8;">${escapeHtml(st.diff_with_previous)}</div>
                            </div>
                        ` : ''}
                    </div>
                `;
            });
            container.innerHTML = html;
        }

        if (btnOpenStages) btnOpenStages.addEventListener('click', loadStages);
        if (btnRefreshStages) btnRefreshStages.addEventListener('click', loadStages);
        if (btnCloseStages) btnCloseStages.addEventListener('click', () => modalStages?.classList.add('hidden'));
        if (btnDismissStages) btnDismissStages.addEventListener('click', () => modalStages?.classList.add('hidden'));

        // --- 2. Chunk Reviewer & Editor ---
        const btnOpenChunks = document.getElementById('btn-open-chunks-modal');
        const modalChunks = document.getElementById('chunks-modal');
        const btnCloseChunks = document.getElementById('btn-close-chunks-modal');
        const btnDismissChunks = document.getElementById('btn-dismiss-chunks-modal');
        const btnFilterChunks = document.getElementById('btn-filter-chunks');
        const btnMergeSelected = document.getElementById('btn-merge-selected-chunks');
        const btnPrevPage = document.getElementById('btn-chunks-prev-page');
        const btnNextPage = document.getElementById('btn-chunks-next-page');

        const editDrawer = document.getElementById('chunk-edit-drawer');
        const btnCloseDrawer = document.getElementById('btn-close-edit-drawer');
        const btnSaveDrawer = document.getElementById('btn-save-drawer-chunk');
        const btnRevertDrawer = document.getElementById('btn-revert-drawer-chunk');

        async function loadChunks(page = 1) {
            const jid = requireJobId();
            if (!jid) return;
            currentChunkPage = page;
            const q = document.getElementById('chunks-search-input')?.value || '';
            const quality = document.getElementById('chunks-quality-filter')?.value || 'all';
            const cat = document.getElementById('chunks-category-filter')?.value || '';

            const tbody = document.getElementById('dataset-chunks-table-body');
            if (tbody) tbody.innerHTML = '<tr><td colspan="8" class="text-center p-3"><i class="fa-solid fa-spinner fa-spin"></i> Loading chunks...</td></tr>';
            if (modalChunks) modalChunks.classList.remove('hidden');

            try {
                let url = `/api/ai/chunks/${jid}?page=${page}&page_size=15`;
                if (q) url += `&query=${encodeURIComponent(q)}`;
                if (quality) url += `&quality=${encodeURIComponent(quality)}`;
                if (cat) url += `&category=${encodeURIComponent(cat)}`;

                const resp = await fetch(url);
                const res = await resp.json();
                if (!resp.ok) throw new Error(res.detail || 'Error loading chunks');
                renderChunksTable(res.data, jid);
            } catch (err) {
                if (tbody) tbody.innerHTML = `<tr><td colspan="8" class="text-danger p-3">${err.message}</td></tr>`;
            }
        }

        function renderChunksTable(data, jid) {
            const tbody = document.getElementById('dataset-chunks-table-body');
            const pageInfo = document.getElementById('chunks-pagination-info');
            if (pageInfo) pageInfo.textContent = `Page ${data.page} of ${data.total_pages} (${data.total} total chunks)`;

            if (!data.items || data.items.length === 0) {
                tbody.innerHTML = '<tr><td colspan="8" class="empty-state-row"><div class="empty-state">No chunks found.</div></td></tr>';
                return;
            }

            let html = '';
            data.items.forEach(c => {
                const userEditedBadge = c.user_edited
                    ? '<span class="badge badge-info" style="font-size: 0.7rem;">Edited</span>'
                    : '<span style="color: var(--color-text-dim);">-</span>';
                const flagsHtml = (c.quality_flags && c.quality_flags.length > 0)
                    ? c.quality_flags.map(f => `<span class="badge badge-warning" style="font-size: 0.65rem; margin-right: 2px;">${f}</span>`).join('')
                    : '<span style="color: var(--color-text-dim);">Clean</span>';

                html += `
                    <tr data-chunk-row="${c.chunk_id}">
                        <td><input type="checkbox" class="chk-chunk-select" value="${c.chunk_id}" /></td>
                        <td><code style="font-size: 0.75rem;">${c.chunk_id.slice(0, 14)}...</code></td>
                        <td style="font-size: 0.8rem; color: var(--color-text-secondary);">${escapeHtml(c.heading_context || '-')}</td>
                        <td style="font-size: 0.8rem;" dir="auto">${escapeHtml(c.text.slice(0, 100))}${c.text.length > 100 ? '...' : ''}</td>
                        <td>${c.char_count}</td>
                        <td style="font-size: 0.8rem;">${escapeHtml(c.category || '-')}</td>
                        <td>${userEditedBadge}</td>
                        <td>
                            <div class="btn-group">
                                <button type="button" class="btn btn-outline btn-sm btn-edit-chunk-row" title="Edit Chunk" data-cid="${c.chunk_id}">
                                    <i class="fa-solid fa-pen"></i>
                                </button>
                                <button type="button" class="btn btn-outline btn-sm btn-split-chunk-row" title="Split Chunk" data-cid="${c.chunk_id}">
                                    <i class="fa-solid fa-scissors"></i>
                                </button>
                            </div>
                        </td>
                    </tr>
                `;
            });
            tbody.innerHTML = html;

            // Wire row action buttons
            tbody.querySelectorAll('.btn-edit-chunk-row').forEach(b => {
                b.addEventListener('click', () => {
                    const cid = b.getAttribute('data-cid');
                    const target = data.items.find(x => x.chunk_id === cid);
                    if (target) openEditDrawer(target);
                });
            });

            tbody.querySelectorAll('.btn-split-chunk-row').forEach(b => {
                b.addEventListener('click', () => {
                    const cid = b.getAttribute('data-cid');
                    splitChunk(jid, cid);
                });
            });
        }

        function openEditDrawer(chunk) {
            selectedChunkForEdit = chunk;
            document.getElementById('drawer-chunk-id').textContent = chunk.chunk_id;
            document.getElementById('drawer-heading-input').value = chunk.heading_context || '';
            document.getElementById('drawer-category-input').value = chunk.category || '';
            document.getElementById('drawer-text-input').value = chunk.text || '';
            if (editDrawer) editDrawer.classList.remove('hidden');
        }

        if (btnSaveDrawer) {
            btnSaveDrawer.addEventListener('click', async () => {
                const jid = getActiveJobId();
                if (!jid || !selectedChunkForEdit) return;

                const newHeading = document.getElementById('drawer-heading-input').value;
                const newCat = document.getElementById('drawer-category-input').value;
                const newText = document.getElementById('drawer-text-input').value;

                try {
                    const resp = await fetch(`/api/ai/chunks/${jid}/update`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            chunk_id: selectedChunkForEdit.chunk_id,
                            heading_context: newHeading,
                            category: newCat,
                            text: newText,
                        }),
                    });
                    const res = await resp.json();
                    if (!resp.ok) throw new Error(res.detail || 'Error updating chunk');

                    showToast(res.message, res.data.embedding_invalidated ? 'info' : 'success');
                    if (editDrawer) editDrawer.classList.add('hidden');
                    loadChunks(currentChunkPage);
                } catch (err) {
                    showToast(err.message, 'danger');
                }
            });
        }

        if (btnRevertDrawer) {
            btnRevertDrawer.addEventListener('click', async () => {
                const jid = getActiveJobId();
                if (!jid || !selectedChunkForEdit) return;
                try {
                    const resp = await fetch(`/api/ai/chunks/${jid}/revert`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ chunk_id: selectedChunkForEdit.chunk_id }),
                    });
                    const res = await resp.json();
                    if (!resp.ok) throw new Error(res.detail || 'Error reverting chunk');
                    showToast(res.message, 'success');
                    if (editDrawer) editDrawer.classList.add('hidden');
                    loadChunks(currentChunkPage);
                } catch (err) {
                    showToast(err.message, 'danger');
                }
            });
        }

        if (btnMergeSelected) {
            btnMergeSelected.addEventListener('click', async () => {
                const jid = requireJobId();
                if (!jid) return;
                const checked = Array.from(document.querySelectorAll('.chk-chunk-select:checked')).map(el => el.value);
                if (checked.length < 2) {
                    showToast('Select at least two chunks to merge.', 'warning');
                    return;
                }
                if (!confirm(`Are you sure you want to merge the ${checked.length} selected chunks?`)) return;

                try {
                    const resp = await fetch(`/api/ai/chunks/${jid}/merge`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ chunk_ids: checked }),
                    });
                    const res = await resp.json();
                    if (!resp.ok) throw new Error(res.detail || 'Error merging chunks');
                    showToast(res.message, 'success');
                    loadChunks(1);
                } catch (err) {
                    showToast(err.message, 'danger');
                }
            });
        }

        async function splitChunk(jid, chunkId) {
            if (!confirm(`Do you want to split chunk ${chunkId} into two distinct parts?`)) return;
            try {
                const resp = await fetch(`/api/ai/chunks/${jid}/split`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ chunk_id: chunkId }),
                });
                const res = await resp.json();
                if (!resp.ok) throw new Error(res.detail || 'Error splitting chunk');
                showToast(res.message, 'success');
                loadChunks(currentChunkPage);
            } catch (err) {
                showToast(err.message, 'danger');
            }
        }

        if (btnOpenChunks) btnOpenChunks.addEventListener('click', () => loadChunks(1));
        if (btnFilterChunks) btnFilterChunks.addEventListener('click', () => loadChunks(1));
        if (btnCloseChunks) btnCloseChunks.addEventListener('click', () => modalChunks?.classList.add('hidden'));
        if (btnDismissChunks) btnDismissChunks.addEventListener('click', () => modalChunks?.classList.add('hidden'));
        if (btnCloseDrawer) btnCloseDrawer.addEventListener('click', () => editDrawer?.classList.add('hidden'));
        if (btnPrevPage) btnPrevPage.addEventListener('click', () => { if (currentChunkPage > 1) loadChunks(currentChunkPage - 1); });
        if (btnNextPage) btnNextPage.addEventListener('click', () => loadChunks(currentChunkPage + 1));

        // --- 3. Data Quality Report ---
        const btnOpenQuality = document.getElementById('btn-open-quality-modal');
        const modalQuality = document.getElementById('quality-modal');
        const btnCloseQuality = document.getElementById('btn-close-quality-modal');
        const btnDismissQuality = document.getElementById('btn-dismiss-quality-modal');
        const btnRefreshQuality = document.getElementById('btn-refresh-quality');

        async function loadQualityReport() {
            const jid = requireJobId();
            if (!jid) return;
            const container = document.getElementById('quality-report-container');
            if (container) container.innerHTML = '<div class="empty-state"><i class="fa-solid fa-spinner fa-spin"></i> Analyzing metadata and computing data quality metrics...</div>';
            if (modalQuality) modalQuality.classList.remove('hidden');

            try {
                const resp = await fetch(`/api/ai/dataset/${jid}/quality-report`);
                const res = await resp.json();
                if (!resp.ok) throw new Error(res.detail || 'Error fetching quality report');
                renderQualityReport(res.data, container);
            } catch (err) {
                if (container) container.innerHTML = `<div class="empty-state text-danger">${err.message}</div>`;
            }
        }

        function renderQualityReport(rep, container) {
            const docQ = rep.document_quality;
            const vol = rep.content_volume;
            const chunkQ = rep.chunk_telemetry;
            const embQ = rep.embedding_telemetry;

            let warningsHtml = '';
            if (rep.actionable_warnings && rep.actionable_warnings.length > 0) {
                warningsHtml = rep.actionable_warnings.map(w => `
                    <div class="actionable-warning-card severity-${w.severity}">
                        <div style="font-weight: 600; color: var(--color-primary); margin-bottom: 0.25rem;">
                            <i class="fa-solid fa-circle-exclamation"></i> ${escapeHtml(w.category)}: ${escapeHtml(w.message)}
                        </div>
                        <div style="font-size: 0.85rem; color: var(--color-text-secondary);"><i class="fa-solid fa-lightbulb"></i> Suggested Action: ${escapeHtml(w.action)}</div>
                    </div>
                `).join('');
            } else {
                warningsHtml = '<div style="font-size: 0.85rem; color: var(--color-text-secondary);">No structural or quality warnings found. All data within standard thresholds.</div>';
            }

            container.innerHTML = `
                <div class="quality-report-grid">
                    <div class="quality-stat-card">
                        <h4><i class="fa-solid fa-file-shield"></i> Document Quality</h4>
                        <div class="stat-key-val-row"><span class="stat-key">Total Documents:</span><span class="stat-val">${docQ.total_documents}</span></div>
                        <div class="stat-key-val-row"><span class="stat-key">High-Quality Docs:</span><span class="stat-val text-primary">${docQ.quality_distribution.high}</span></div>
                        <div class="stat-key-val-row"><span class="stat-key">Empty Docs:</span><span class="stat-val">${docQ.empty_documents}</span></div>
                        <div class="stat-key-val-row"><span class="stat-key">Duplicate Docs:</span><span class="stat-val">${docQ.duplicate_documents}</span></div>
                    </div>

                    <div class="quality-stat-card">
                        <h4><i class="fa-solid fa-chart-line"></i> Volume & Content Density</h4>
                        <div class="stat-key-val-row"><span class="stat-key">Clean Markdown Characters:</span><span class="stat-val">${vol.cleaned_markdown_characters.toLocaleString()}</span></div>
                        <div class="stat-key-val-row"><span class="stat-key">Estimated Tokens:</span><span class="stat-val">${vol.estimated_tokens.toLocaleString()}</span></div>
                        <div class="stat-key-val-row"><span class="stat-key">Estimated Noise Ratio:</span><span class="stat-val">${vol.estimated_noise_ratio_percent}%</span></div>
                        <div class="stat-key-val-row"><span class="stat-key">Raw-to-Markdown Delta:</span><span class="stat-val">${vol.volume_delta_percent}%</span></div>
                    </div>

                    <div class="quality-stat-card">
                        <h4><i class="fa-solid fa-scissors"></i> Chunking & Segments</h4>
                        <div class="stat-key-val-row"><span class="stat-key">Total Chunks:</span><span class="stat-val">${chunkQ.total_chunks}</span></div>
                        <div class="stat-key-val-row"><span class="stat-key">Average Chunk Size:</span><span class="stat-val">${chunkQ.average_chunk_size} chars</span></div>
                        <div class="stat-key-val-row"><span class="stat-key">User-Edited Chunks:</span><span class="stat-val text-primary">${chunkQ.user_edited_chunks}</span></div>
                        <div class="stat-key-val-row"><span class="stat-key">Size Distribution:</span><span class="stat-val">&lt;300: ${chunkQ.size_histogram['<300']} | 300-800: ${chunkQ.size_histogram['300-800']}</span></div>
                    </div>

                    <div class="quality-stat-card">
                        <h4><i class="fa-solid fa-network-wired"></i> Vector Embeddings</h4>
                        <div class="stat-key-val-row"><span class="stat-key">Embedded Chunks:</span><span class="stat-val text-primary">${embQ.embedded_chunks} / ${embQ.total_chunks}</span></div>
                        <div class="stat-key-val-row"><span class="stat-key">Pending Embeddings:</span><span class="stat-val">${embQ.pending_embeddings}</span></div>
                        <div class="stat-key-val-row"><span class="stat-key">Embedding Model:</span><span class="stat-val">${embQ.embedding_model || 'Not set'}</span></div>
                    </div>
                </div>

                <div class="quality-stat-card" style="margin-bottom: 1rem;">
                    <h4><i class="fa-solid fa-triangle-exclamation"></i> Actionable Warnings</h4>
                    ${warningsHtml}
                </div>

                <div style="font-size: 0.78rem; color: var(--color-text-muted); background: #0a0a0a; padding: 0.75rem; border-radius: 6px;">
                    <i class="fa-solid fa-info-circle text-primary"></i> <strong>Metric Resolution:</strong> Document counts, characters, and hash digests are calculated deterministically; token budget and boilerplate noise estimates are statistical approximations.
                </div>
            `;
        }

        if (btnOpenQuality) btnOpenQuality.addEventListener('click', loadQualityReport);
        if (btnRefreshQuality) btnRefreshQuality.addEventListener('click', loadQualityReport);
        if (btnCloseQuality) btnCloseQuality.addEventListener('click', () => modalQuality?.classList.add('hidden'));
        if (btnDismissQuality) btnDismissQuality.addEventListener('click', () => modalQuality?.classList.add('hidden'));

        // --- 4. Dataset Versioning & Diff ---
        const btnOpenVersion = document.getElementById('btn-open-version-modal');
        const modalVersion = document.getElementById('version-modal');
        const btnCloseVersion = document.getElementById('btn-close-version-modal');
        const btnDismissVersion = document.getElementById('btn-dismiss-version-modal');
        const btnCreateSnapshot = document.getElementById('btn-create-snapshot');
        const btnRunDiff = document.getElementById('btn-run-version-diff');

        async function initVersionModal() {
            const jid = requireJobId();
            if (!jid) return;
            if (modalVersion) modalVersion.classList.remove('hidden');

            try {
                const resp = await fetch(`/api/ai/dataset/${jid}/versions`);
                const res = await resp.json();
                if (!resp.ok) throw new Error(res.detail || 'Error fetching snapshots');
                populateVersionSelects(res.data.snapshots);
            } catch (err) {
                showToast(err.message, 'danger');
            }
        }

        function populateVersionSelects(snapshots) {
            const sel1 = document.getElementById('select-diff-v1');
            const sel2 = document.getElementById('select-diff-v2');
            if (!sel1 || !sel2) return;

            sel1.innerHTML = '';
            sel2.innerHTML = '<option value="current">Current State (Live)</option>';

            if (!snapshots || snapshots.length === 0) {
                sel1.innerHTML = '<option value="">No snapshots recorded</option>';
                return;
            }

            snapshots.forEach(s => {
                const opt1 = document.createElement('option');
                opt1.value = s.version;
                opt1.textContent = `${s.version} (${s.chunk_count} chunks)`;
                sel1.appendChild(opt1);

                const opt2 = document.createElement('option');
                opt2.value = s.version;
                opt2.textContent = `${s.version} (${s.chunk_count} chunks)`;
                sel2.appendChild(opt2);
            });
        }

        if (btnCreateSnapshot) {
            btnCreateSnapshot.addEventListener('click', async () => {
                const jid = requireJobId();
                if (!jid) return;
                const label = document.getElementById('input-snapshot-label')?.value.trim();
                const desc = document.getElementById('input-snapshot-desc')?.value.trim();

                try {
                    const resp = await fetch(`/api/ai/dataset/${jid}/versions/snapshot`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ version_label: label || null, description: desc || null }),
                    });
                    const res = await resp.json();
                    if (!resp.ok) throw new Error(res.detail || 'Error creating snapshot');
                    showToast(res.message, 'success');
                    initVersionModal();
                } catch (err) {
                    showToast(err.message, 'danger');
                }
            });
        }

        if (btnRunDiff) {
            btnRunDiff.addEventListener('click', async () => {
                const jid = requireJobId();
                if (!jid) return;
                const v1 = document.getElementById('select-diff-v1')?.value;
                const v2 = document.getElementById('select-diff-v2')?.value || 'current';
                if (!v1) {
                    showToast('Please select a valid baseline snapshot first.', 'warning');
                    return;
                }

                const out = document.getElementById('version-diff-output');
                if (out) out.innerHTML = '<div class="empty-state"><i class="fa-solid fa-spinner fa-spin"></i> Analyzing text and metadata differences...</div>';

                try {
                    const resp = await fetch(`/api/ai/dataset/${jid}/versions/diff`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ v1, v2 }),
                    });
                    const res = await resp.json();
                    if (!resp.ok) throw new Error(res.detail || 'Diff error');
                    renderDiffOutput(res.data, out);
                } catch (err) {
                    if (out) out.innerHTML = `<div class="empty-state text-danger">${err.message}</div>`;
                }
            });
        }

        function renderDiffOutput(diffData, container) {
            const s = diffData.summary;
            let modHtml = '';
            if (diffData.modified_chunks && diffData.modified_chunks.length > 0) {
                modHtml = diffData.modified_chunks.map(m => `
                    <div class="actionable-warning-card" style="margin-bottom: 0.5rem;">
                        <div style="font-size: 0.85rem; font-weight: 600; display: flex; justify-content: space-between;">
                            <span>ID: <code>${m.chunk_id}</code></span>
                            <span>${m.text_changed ? '<span class="badge badge-warning">Text Changed (Re-embedding Needed)</span>' : '<span class="badge badge-info">Metadata Only (Vector Retained)</span>'}</span>
                        </div>
                        ${m.diff ? `<pre class="stage-preview-box" style="margin-top: 0.5rem; max-height: 120px;">${escapeHtml(m.diff)}</pre>` : ''}
                    </div>
                `).join('');
            } else {
                modHtml = '<div style="font-size: 0.85rem; color: var(--color-text-secondary);">No modified chunks between these two versions.</div>';
            }

            container.innerHTML = `
                <div class="diff-stat-chip-row">
                    <div class="diff-chip"><i class="fa-solid fa-plus text-primary"></i> Added: ${s.added_count}</div>
                    <div class="diff-chip"><i class="fa-solid fa-minus text-danger"></i> Removed: ${s.removed_count}</div>
                    <div class="diff-chip"><i class="fa-solid fa-pen-to-square"></i> Modified: ${s.modified_count}</div>
                    <div class="diff-chip"><i class="fa-solid fa-equals"></i> Unchanged: ${s.unchanged_count}</div>
                    <div class="diff-chip cost-saving"><i class="fa-solid fa-coins"></i> Retained Vectors (Saved): ${s.cost_saving_retained_embeddings_count}</div>
                    <div class="diff-chip" style="border-color: var(--color-primary-border);"><i class="fa-solid fa-bolt text-primary"></i> Re-embedding Needed: ${s.re_embedding_needed_count}</div>
                </div>

                <div class="quality-stat-card">
                    <h4><i class="fa-solid fa-code-compare"></i> Chunk Modification Details:</h4>
                    ${modHtml}
                </div>
            `;
        }

        if (btnOpenVersion) btnOpenVersion.addEventListener('click', initVersionModal);
        if (btnCloseVersion) btnCloseVersion.addEventListener('click', () => modalVersion?.classList.add('hidden'));
        if (btnDismissVersion) btnDismissVersion.addEventListener('click', () => modalVersion?.classList.add('hidden'));

        // --- 5. Export Manifest ---
        const btnDownloadManifest = document.getElementById('btn-download-manifest');
        if (btnDownloadManifest) {
            btnDownloadManifest.addEventListener('click', () => {
                const jid = requireJobId();
                if (!jid) return;
                window.location.href = `/api/ai/dataset/${jid}/manifest/download`;
            });
        }
    }


    // ========================================================================
    // PHASE 3: RAG RETRIEVAL EVALUATION, PLAYGROUND & DEBUGGING STUDIO
    // ========================================================================

    // ========================================================================
    // PHASE 3: RAG RETRIEVAL EVALUATION, PLAYGROUND & DEBUGGING STUDIO
    // ========================================================================
    function initEvalStudio() {
        console.log('[EvalStudio] Initializing Phase 3 Retrieval Evaluation Studio...');

        let activeEvalJobId = '';
        let currentEvalDatasets = [];
        let selectedDatasetId = '';
        let lastRunResults = [];

        // Cached results for instant bilingual re-rendering on language switch
        let lastPlaygroundData = null;
        let lastCompareData = null;
        let lastDatasetDetails = null;
        let lastRunData = null;
        let lastDiffData = null;
        let lastTraceData = null;

        function resolveJobId() {
            const inputVal = document.getElementById('eval-job-id-input')?.value?.trim();
            if (inputVal && /^[0-9a-fA-F-]{8,}$/.test(inputVal)) return inputVal;

            const selectVal = document.getElementById('eval-job-select')?.value?.trim();
            if (selectVal && /^[0-9a-fA-F-]{8,}$/.test(selectVal)) return selectVal;

            if (state.extractionJobId && /^[0-9a-fA-F-]{8,}$/.test(state.extractionJobId)) {
                return state.extractionJobId;
            }
            if (state.discoveryJobId && /^[0-9a-fA-F-]{8,}$/.test(state.discoveryJobId)) {
                return state.discoveryJobId;
            }

            const domText = document.getElementById('ai-studio-job-id')?.textContent?.trim();
            if (domText && /^[0-9a-fA-F-]{8,}$/.test(domText)) {
                return domText;
            }

            const headerBadge = document.getElementById('ai-active-job-id')?.textContent?.trim();
            if (headerBadge && /^[0-9a-fA-F-]{8,}$/.test(headerBadge)) {
                return headerBadge;
            }
            return inputVal || selectVal || '';
        }

        // --- Sub-navigation Switching ---
        const subnavBtns = document.querySelectorAll('.eval-subnav-btn');
        const subpanels = document.querySelectorAll('.eval-subpanel');

        subnavBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const subtab = btn.getAttribute('data-subtab');
                subnavBtns.forEach(b => {
                    const isActive = b === btn;
                    b.classList.toggle('active', isActive);
                    b.setAttribute('aria-selected', isActive ? 'true' : 'false');
                });
                subpanels.forEach(panel => {
                    const isTarget = panel.id === `eval-subpanel-${subtab}`;
                    panel.classList.toggle('active', isTarget);
                    panel.classList.remove('hidden');
                });

                if (subtab === 'datasets') loadEvalDatasets();
                if (subtab === 'runs') refreshRunsDropdowns();
                if (subtab === 'diff') refreshRunsDropdowns();
            });
        });

        // Populate available jobs into dropdown
        async function loadAvailableJobs() {
            const jobSelect = document.getElementById('eval-job-select');
            if (!jobSelect) return;
            try {
                const resp = await fetch('/api/jobs/list');
                if (!resp.ok) return;
                const jobs = await resp.json();
                if (!Array.isArray(jobs) || jobs.length === 0) return;

                const defaultOptionText = t('eval_job_select_default', '(Select from executed jobs...)');
                jobSelect.innerHTML = `<option value="">${defaultOptionText}</option>`;
                jobs.forEach(j => {
                    const opt = document.createElement('option');
                    opt.value = j.job_id;
                    const typeLabel = j.job_type === 'extract' ? t('nav_extract', 'Extract') : (j.job_type === 'crawl' ? t('nav_discover', 'Discover') : j.job_type);
                    opt.textContent = `${t('metric_job_id', 'Job')} ${j.job_id.slice(0, 8)} (${typeLabel} - ${j.status})`;
                    jobSelect.appendChild(opt);
                });

                // Auto-select active job or first job
                const currentJobId = resolveJobId();
                if (currentJobId) {
                    jobSelect.value = currentJobId;
                    const jobInput = document.getElementById('eval-job-id-input');
                    if (jobInput) jobInput.value = currentJobId;
                    activeEvalJobId = currentJobId;
                    loadDatasetSnapshots(currentJobId);
                } else if (jobs.length > 0) {
                    jobSelect.value = jobs[0].job_id;
                    const jobInput = document.getElementById('eval-job-id-input');
                    if (jobInput) jobInput.value = jobs[0].job_id;
                    activeEvalJobId = jobs[0].job_id;
                    loadDatasetSnapshots(jobs[0].job_id);
                }
            } catch (err) {
                console.warn('[EvalStudio] Failed loading jobs list:', err);
            }
        }

        const jobSelectEl = document.getElementById('eval-job-select');
        if (jobSelectEl) {
            jobSelectEl.addEventListener('change', () => {
                const chosen = jobSelectEl.value;
                const jobInput = document.getElementById('eval-job-id-input');
                if (jobInput) jobInput.value = chosen;
                activeEvalJobId = chosen;
                loadDatasetSnapshots(chosen);
            });
        }

        // Use Active Job Button
        const btnUseActiveJob = document.getElementById('btn-eval-use-active-job');
        if (btnUseActiveJob) {
            btnUseActiveJob.addEventListener('click', () => {
                const jid = resolveJobId();
                const jobInput = document.getElementById('eval-job-id-input');
                if (jobInput) jobInput.value = jid;
                if (jobSelectEl && jid) jobSelectEl.value = jid;
                activeEvalJobId = jid;
                loadDatasetSnapshots(jid);
            });
        }

        const jobInput = document.getElementById('eval-job-id-input');
        if (jobInput) {
            jobInput.addEventListener('change', () => {
                activeEvalJobId = jobInput.value.trim();
                loadDatasetSnapshots(activeEvalJobId);
            });
        }

        async function loadDatasetSnapshots(jobId) {
            const sel = document.getElementById('eval-version-select');
            if (!sel || !jobId) return;
            const currentLiveText = t('eval_version_current', 'Current Live Chunks');
            sel.innerHTML = `<option value="">${currentLiveText}</option>`;
            try {
                const resp = await fetch(`/api/ai/dataset/${jobId}/snapshots`);
                if (!resp.ok) return;
                const res = await resp.json();
                if (res.data && Array.isArray(res.data)) {
                    res.data.forEach(s => {
                        const opt = document.createElement('option');
                        opt.value = s.version;
                        opt.textContent = `${t('eval_version_lbl', 'Version')} ${s.version} (${s.chunk_count} ${t('eval_pg_chunks_unit', 'chunks')}) - ${s.description}`;
                        sel.appendChild(opt);
                    });
                }
            } catch (_) {}
        }

        // --- Sub-panel 1: Playground Search ---
        let selectedMethod = 'hybrid';
        const methodBtns = document.querySelectorAll('#pg-method-selector .segmented-btn');
        const alphaGroup = document.getElementById('pg-alpha-group');

        methodBtns.forEach(b => {
            b.addEventListener('click', () => {
                methodBtns.forEach(x => x.classList.remove('active'));
                b.classList.add('active');
                selectedMethod = b.getAttribute('data-method');
                if (alphaGroup) {
                    alphaGroup.style.display = (selectedMethod === 'hybrid') ? '' : 'none';
                }
            });
        });

        const bindSlider = (id, valId) => {
            const el = document.getElementById(id);
            const valEl = document.getElementById(valId);
            if (el && valEl) {
                el.addEventListener('input', () => {
                    valEl.textContent = (id === 'pg-alpha-input' || id === 'pg-minscore-input') ? parseFloat(el.value).toFixed(2) : el.value;
                });
            }
        };
        bindSlider('pg-topk-input', 'pg-topk-val');
        bindSlider('pg-alpha-input', 'pg-alpha-val');
        bindSlider('pg-minscore-input', 'pg-minscore-val');

        const btnRunPlayground = document.getElementById('btn-run-playground-search');
        if (btnRunPlayground) {
            btnRunPlayground.addEventListener('click', async () => {
                const jid = resolveJobId();
                if (!jid) {
                    showToast(t('eval_job_placeholder', 'Job ID') + ': ' + t('eval_toast_enter_job', 'Please enter a valid Job ID.'), 'warning');
                    return;
                }
                const query = document.getElementById('pg-query-input')?.value?.trim();
                if (!query) {
                    showToast(t('eval_toast_enter_query', 'Query text cannot be empty.'), 'warning');
                    return;
                }

                const topK = parseInt(document.getElementById('pg-topk-input')?.value || '5', 10);
                const alpha = parseFloat(document.getElementById('pg-alpha-input')?.value || '0.7');
                const minScore = parseFloat(document.getElementById('pg-minscore-input')?.value || '0.0');
                const category = document.getElementById('pg-filter-category')?.value?.trim() || null;
                const sourceUrl = document.getElementById('pg-filter-url')?.value?.trim() || null;
                const expandNeighbors = document.getElementById('pg-expand-neighbors')?.checked || false;
                const versionLabel = document.getElementById('eval-version-select')?.value || null;

                const resultsArea = document.getElementById('pg-results-area');
                if (resultsArea) {
                    resultsArea.innerHTML = `<div class="empty-state"><i class="fa-solid fa-spinner fa-spin empty-icon"></i><p>${t('eval_pg_searching', 'Running retrieval query...')}</p></div>`;
                }

                try {
                    const resp = await fetch('/api/ai/eval/playground', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            job_id: jid,
                            query,
                            method: selectedMethod,
                            top_k: topK,
                            alpha,
                            min_score: minScore,
                            category,
                            source_url: sourceUrl,
                            expand_neighbors: expandNeighbors,
                            version_label: versionLabel,
                        }),
                    });

                    const res = await resp.json();
                    if (!resp.ok) throw new Error(res.detail || 'Error in retrieval search');
                    lastPlaygroundData = res.data;
                    renderPlaygroundResults(res.data, resultsArea);
                } catch (err) {
                    if (resultsArea) {
                        resultsArea.innerHTML = `<div class="eval-alert-danger"><i class="fa-solid fa-triangle-exclamation"></i><span>${escapeHtml(err.message)}</span></div>`;
                    }
                }
            });
        }

        function renderPlaygroundResults(data, container) {
            if (!container) return;
            if (!data || !data.results || data.results.length === 0) {
                container.innerHTML = `
                    <div class="empty-state">
                        <i class="fa-solid fa-filter-circle-xmark empty-icon"></i>
                        <p>${t('eval_pg_no_results', 'No chunks retrieved matching this query and score threshold.')}</p>
                        <small style="color:var(--color-text-secondary);">${t('eval_pg_adjust_hint', 'Lower the min_score threshold or adjust metadata filters.')}</small>
                    </div>`;
                return;
            }

            const headerHtml = `
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem; flex-wrap:wrap; gap:0.5rem;">
                    <span style="font-size:0.85rem; color:var(--color-text-secondary);">
                        ${t('eval_pg_total_results', 'Results:')} <strong>${data.total_returned}</strong> ${t('eval_pg_candidates_of', 'of')} ${data.total_candidates_considered} ${t('eval_pg_candidates_considered', 'candidates')} (${t('eval_pg_latency', 'Latency:')} ${data.latency_ms}ms)
                    </span>
                    <span class="score-badge score-badge-${data.method}">${t('eval_pg_method_lbl', 'Method:')} ${data.method.toUpperCase()}</span>
                </div>
            `;

            const cardsHtml = data.results.map(r => `
                <div class="eval-result-card">
                    <div class="eval-result-card-header">
                        <div style="display:flex; align-items:center; gap:0.5rem;">
                            <span class="eval-rank-pill">#${r.rank}</span>
                            <span class="score-badge score-badge-${r.search_method}">
                                <i class="fa-solid fa-star-half-stroke"></i> ${t('eval_pg_score', 'Score:')} ${r.score}
                            </span>
                            <span style="font-size:0.75rem; color:var(--color-text-secondary);">(${r.score_type})</span>
                        </div>
                        <span style="font-size:0.75rem; color:var(--color-text-secondary); font-family:var(--font-code);" dir="ltr">ID: ${r.chunk_id}</span>
                    </div>

                    ${r.heading_context ? `<div class="eval-result-heading"><i class="fa-solid fa-heading text-primary"></i> ${escapeHtml(r.heading_context)}</div>` : ''}

                    <div class="eval-result-text" dir="auto">${escapeHtml(r.text_preview)}</div>

                    <div class="eval-result-footer">
                        <span><i class="fa-solid fa-link"></i> ${t('eval_pg_source', 'Source:')} <a href="${escapeHtml(r.source_url)}" target="_blank" rel="noopener" style="color:var(--color-primary);" dir="ltr">${escapeHtml(r.source_url || t('eval_pg_source_file', 'File Document'))}</a></span>
                        <span>${t('eval_pg_chars', 'Chars:')} ${r.char_count}</span>
                    </div>

                    ${r.neighbors_count > 0 ? `
                        <div class="eval-neighbors-container">
                            <strong style="font-size:0.78rem; color:var(--color-primary);"><i class="fa-solid fa-arrows-left-right-to-line"></i> ${t('eval_pg_neighbors_ctx', 'Attached Neighbor Context')} (${r.neighbors_count} ${t('eval_pg_chunks_unit', 'chunks')}):</strong>
                            ${r.neighbors_previews.map(np => `<div class="eval-neighbor-item" dir="auto">${escapeHtml(np)}</div>`).join('')}
                        </div>
                    ` : ''}
                </div>
            `).join('');

            container.innerHTML = headerHtml + cardsHtml;
        }

        // --- Sub-panel 2: Method Comparison ---
        const btnRunMethodCompare = document.getElementById('btn-run-method-compare');
        if (btnRunMethodCompare) {
            btnRunMethodCompare.addEventListener('click', async () => {
                const jid = resolveJobId();
                if (!jid) {
                    showToast(t('eval_job_placeholder', 'Job ID') + ': ' + t('eval_toast_enter_job', 'Please enter a valid Job ID.'), 'warning');
                    return;
                }
                const query = document.getElementById('cmp-query-input')?.value?.trim();
                if (!query) {
                    showToast(t('eval_toast_enter_query', 'Please enter query text.'), 'warning');
                    return;
                }

                const container = document.getElementById('cmp-results-area');
                if (container) {
                    container.innerHTML = `<div class="empty-state" style="grid-column:1/-1;"><i class="fa-solid fa-spinner fa-spin empty-icon"></i><p>${t('eval_cmp_notice', 'Benchmarking 3 retrieval methods...')}</p></div>`;
                }

                try {
                    const resp = await fetch('/api/ai/eval/playground/compare', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            job_id: jid,
                            query,
                            top_k: 5,
                            alpha: 0.7,
                            version_label: document.getElementById('eval-version-select')?.value || null,
                        }),
                    });
                    const res = await resp.json();
                    if (!resp.ok) throw new Error(res.detail || 'Error in method comparison');
                    lastCompareData = res.data;
                    renderMethodComparison(res.data, container);
                } catch (err) {
                    if (container) {
                        container.innerHTML = `<div class="eval-alert-danger" style="grid-column:1/-1;"><i class="fa-solid fa-triangle-exclamation"></i><span>${escapeHtml(err.message)}</span></div>`;
                    }
                }
            });
        }

        function renderMethodComparison(data, container) {
            if (!container) return;
            if (!data) return;

            const renderCol = (title, icon, badgeClass, results, statusMsg) => `
                <div class="method-compare-col">
                    <div class="method-col-header">
                        <h4><i class="${icon} text-primary"></i> ${title}</h4>
                        <div class="method-col-status">${statusMsg || ''}</div>
                    </div>
                    <div style="display:flex; flex-direction:column; gap:0.6rem;">
                        ${results.length === 0 ? `<div style="color:var(--color-text-secondary); font-size:0.85rem; padding:1rem; text-align:center;">${t('eval_cmp_no_results', 'No results found.')}</div>` : ''}
                        ${results.map(r => `
                            <div class="eval-result-card" style="padding:0.6rem;">
                                <div style="display:flex; justify-content:space-between; margin-bottom:0.3rem;">
                                    <span class="eval-rank-pill">#${r.rank}</span>
                                    <span class="score-badge ${badgeClass}">${r.score}</span>
                                </div>
                                <div style="font-size:0.8rem; line-height:1.5; color:var(--color-text); max-height:80px; overflow:hidden;" dir="auto">
                                    ${escapeHtml(r.text_preview)}
                                </div>
                                <div style="font-size:0.7rem; color:var(--color-text-secondary); margin-top:0.3rem; font-family:var(--font-code);" dir="ltr">ID: ${r.chunk_id}</div>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;

            container.innerHTML = `
                ${renderCol(t('eval_cmp_col_dense', 'Dense Semantic Search'), 'fa-solid fa-brain', 'score-badge-dense', data.dense_results, data.dense_status_message)}
                ${renderCol(t('eval_cmp_col_bm25', 'BM25 Lexical Search'), 'fa-solid fa-align-left', 'score-badge-bm25', data.bm25_results, t('eval_cmp_bm25_subtitle', 'Keyword lexical matching (offline)'))}
                ${renderCol(t('eval_cmp_col_hybrid', 'Hybrid Search'), 'fa-solid fa-shuffle', 'score-badge-hybrid', data.hybrid_results, `${t('eval_cmp_hybrid_subtitle', 'Weighted rank fusion')} (α=${data.alpha})`)}
            `;
        }

        // --- Sub-panel 3: Eval Datasets & QA ---
        async function loadEvalDatasets() {
            const selectEl = document.getElementById('eval-dataset-select');
            const runSelectEl = document.getElementById('run-dataset-select');
            if (!selectEl) return;

            try {
                const resp = await fetch('/api/ai/eval/datasets');
                if (!resp.ok) return;
                const res = await resp.json();
                currentEvalDatasets = res.data || [];

                selectEl.innerHTML = '';
                if (runSelectEl) runSelectEl.innerHTML = '';

                if (currentEvalDatasets.length === 0) {
                    const noDatasetsText = t('eval_ds_select_none', 'No evaluation datasets created yet');
                    selectEl.innerHTML = `<option value="">${noDatasetsText}</option>`;
                    if (runSelectEl) runSelectEl.innerHTML = `<option value="">${noDatasetsText}</option>`;
                    renderDatasetSummary(null);
                    return;
                }

                currentEvalDatasets.forEach(d => {
                    const opt = document.createElement('option');
                    opt.value = d.dataset_id;
                    opt.textContent = `${d.name} (${d.total_samples} ${t('eval_ds_stat_total', 'samples')})`;
                    selectEl.appendChild(opt);

                    if (runSelectEl) {
                        const opt2 = opt.cloneNode(true);
                        runSelectEl.appendChild(opt2);
                    }
                });

                selectedDatasetId = currentEvalDatasets[0].dataset_id;
                selectEl.value = selectedDatasetId;
                loadDatasetDetails(selectedDatasetId);
            } catch (err) {
                console.error('[EvalStudio] Failed loading datasets:', err);
            }
        }

        const datasetSelect = document.getElementById('eval-dataset-select');
        if (datasetSelect) {
            datasetSelect.addEventListener('change', () => {
                selectedDatasetId = datasetSelect.value;
                if (selectedDatasetId) loadDatasetDetails(selectedDatasetId);
            });
        }

        async function loadDatasetDetails(dsId) {
            if (!dsId) return;
            try {
                const resp = await fetch(`/api/ai/eval/datasets/${dsId}`);
                if (!resp.ok) return;
                const res = await resp.json();
                const ds = res.data;
                lastDatasetDetails = ds;
                renderDatasetSummary(ds);
                renderSamplesTable(ds);
            } catch (err) {
                console.error('[EvalStudio] Failed loading dataset details:', err);
            }
        }

        function renderDatasetSummary(ds) {
            const box = document.getElementById('eval-dataset-summary-box');
            if (!box) return;
            if (!ds) {
                box.innerHTML = '';
                return;
            }
            const gtCount = (ds.samples || []).filter(s => (s.expected_chunk_ids && s.expected_chunk_ids.length > 0) || (s.expected_source_urls && s.expected_source_urls.length > 0) || Object.keys(s.relevance_labels || {}).length > 0).length;
            const reviewedCount = (ds.samples || []).filter(s => s.human_reviewed).length;
            const isFa = (state.currentLang === 'fa');

            box.innerHTML = `
                <div class="diff-stat-chip-row">
                    <div class="diff-chip"><i class="fa-solid fa-list-ol text-primary"></i> ${t('eval_ds_stat_total', 'Total Samples:')} ${ds.samples?.length || 0}</div>
                    <div class="diff-chip cost-saving"><i class="fa-solid fa-stamp"></i> ${t('eval_ds_stat_has_gt', 'With Ground Truth:')} ${gtCount}</div>
                    <div class="diff-chip"><i class="fa-solid fa-user-check text-primary"></i> ${t('eval_ds_stat_reviewed', 'Human Reviewed:')} ${reviewedCount}</div>
                    <div class="diff-chip"><i class="fa-solid fa-calendar text-muted"></i> ${t('eval_ds_stat_created', 'Created:')} ${new Date(ds.created_at).toLocaleDateString('en-US')}</div>
                </div>
                ${ds.description ? `<p style="font-size:0.85rem; color:var(--color-text-secondary); margin:0;" dir="auto">${escapeHtml(ds.description)}</p>` : ''}
            `;
        }

        function renderSamplesTable(ds) {
            const tbody = document.getElementById('eval-samples-tbody');
            if (!tbody) return;
            if (!ds.samples || ds.samples.length === 0) {
                tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted" style="padding:1.5rem;">${t('eval_ds_table_empty', 'No test queries registered in this dataset yet.')}</td></tr>`;
                return;
            }

            tbody.innerHTML = ds.samples.map(s => {
                const hasGt = (s.expected_chunk_ids && s.expected_chunk_ids.length > 0) || (s.expected_source_urls && s.expected_source_urls.length > 0) || Object.keys(s.relevance_labels || {}).length > 0;
                const originLabel = s.origin === 'llm_generated' ? `<span class="badge badge-info"><i class="fa-solid fa-robot"></i> ${t('eval_origin_ai', 'AI Generated')}</span>` : (s.origin === 'real' ? `<span class="badge badge-secondary">${t('eval_origin_real', 'Real User')}</span>` : `<span class="badge badge-secondary">${t('eval_origin_manual', 'Manual')}</span>`);
                const gtLabel = hasGt ? `<span class="badge badge-success" title="${(s.expected_chunk_ids || []).join(', ')}">${t('eval_gt_has', 'Available')} (${(s.expected_chunk_ids || []).length} ${t('eval_pg_chunks_unit', 'chunks')})</span>` : `<span class="badge badge-danger">${t('eval_gt_none', 'No Label')}</span>`;
                const reviewedLabel = s.human_reviewed ? `<span class="badge badge-primary"><i class="fa-solid fa-check"></i> ${t('eval_review_verified', 'Verified')}</span>` : `<span class="badge badge-warning">${t('eval_review_pending', 'Pending Review')}</span>`;

                return `
                    <tr>
                        <td><code dir="ltr">${s.sample_id}</code></td>
                        <td style="max-width:280px;" dir="auto"><strong>${escapeHtml(s.question)}</strong></td>
                        <td>${originLabel}</td>
                        <td>${gtLabel}</td>
                        <td>${reviewedLabel}</td>
                        <td>
                            <button type="button" class="btn btn-outline btn-xs btn-edit-sample" data-sample='${JSON.stringify(s)}' title="${t('eval_btn_review', 'Review')}">
                                <i class="fa-solid fa-pen-to-square"></i> ${t('eval_btn_review', 'Review')}
                            </button>
                            <button type="button" class="btn btn-outline btn-xs text-danger btn-del-sample" data-id="${s.sample_id}" title="${t('eval_btn_delete', 'Delete')}">
                                <i class="fa-solid fa-trash"></i>
                            </button>
                        </td>
                    </tr>
                `;
            }).join('');

            tbody.querySelectorAll('.btn-del-sample').forEach(b => {
                b.addEventListener('click', async () => {
                    const sid = b.getAttribute('data-id');
                    if (!confirm(t('eval_toast_confirm_del_sample', 'Are you sure you want to delete this evaluation sample?'))) return;
                    try {
                        const resp = await fetch(`/api/ai/eval/datasets/${selectedDatasetId}/samples/${sid}`, { method: 'DELETE' });
                        if (resp.ok) loadDatasetDetails(selectedDatasetId);
                    } catch (_) {}
                });
            });

            tbody.querySelectorAll('.btn-edit-sample').forEach(b => {
                b.addEventListener('click', () => {
                    const sample = JSON.parse(b.getAttribute('data-sample'));
                    openReviewModal(sample);
                });
            });
        }

        // Create Dataset Modal
        const modalCreateDs = document.getElementById('modal-create-dataset');
        const btnOpenCreateDs = document.getElementById('btn-open-create-dataset-modal');
        const btnCloseCreateDs = document.getElementById('btn-close-create-dataset-modal');
        const btnDismissCreateDs = document.getElementById('btn-dismiss-create-dataset-modal');
        const btnConfirmCreateDs = document.getElementById('btn-confirm-create-dataset');

        if (btnOpenCreateDs) btnOpenCreateDs.addEventListener('click', () => modalCreateDs?.classList.remove('hidden'));
        if (btnCloseCreateDs) btnCloseCreateDs.addEventListener('click', () => modalCreateDs?.classList.add('hidden'));
        if (btnDismissCreateDs) btnDismissCreateDs.addEventListener('click', () => modalCreateDs?.classList.add('hidden'));

        if (btnConfirmCreateDs) {
            btnConfirmCreateDs.addEventListener('click', async () => {
                const name = document.getElementById('new-dataset-name')?.value?.trim();
                const desc = document.getElementById('new-dataset-desc')?.value?.trim();
                if (!name) {
                    showToast(t('eval_modal_cd_name_lbl', 'Dataset name is required.'), 'warning');
                    return;
                }
                try {
                    const resp = await fetch('/api/ai/eval/datasets', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name, description: desc, job_id: resolveJobId() }),
                    });
                    if (resp.ok) {
                        modalCreateDs?.classList.add('hidden');
                        document.getElementById('new-dataset-name').value = '';
                        document.getElementById('new-dataset-desc').value = '';
                        showToast(t('eval_modal_cd_title', 'Evaluation dataset created successfully.'), 'success');
                        await loadEvalDatasets();
                    }
                } catch (err) {
                    showToast(err.message, 'danger');
                }
            });
        }

        // Delete Dataset
        const btnDeleteDs = document.getElementById('btn-delete-active-dataset');
        if (btnDeleteDs) {
            btnDeleteDs.addEventListener('click', async () => {
                if (!selectedDatasetId) return;
                if (!confirm(t('eval_toast_confirm_del_ds', 'Are you sure you want to delete this evaluation dataset and all its samples?'))) return;
                try {
                    const resp = await fetch(`/api/ai/eval/datasets/${selectedDatasetId}`, { method: 'DELETE' });
                    if (resp.ok) {
                        showToast(t('eval_toast_ds_deleted', 'Evaluation dataset deleted.'), 'info');
                        await loadEvalDatasets();
                    }
                } catch (_) {}
            });
        }

        // Import Synthetic QA
        const btnImportQa = document.getElementById('btn-open-import-qa-modal');
        if (btnImportQa) {
            btnImportQa.addEventListener('click', async () => {
                if (!selectedDatasetId) {
                    showToast(t('eval_ds_select_lbl', 'Please select an evaluation dataset first.'), 'warning');
                    return;
                }
                const jid = resolveJobId();
                if (!jid) {
                    showToast(t('eval_job_placeholder', 'Valid Job ID not found.'), 'warning');
                    return;
                }

                if (!confirm(t('eval_toast_confirm_import_qa', 'Synthetic Q&A pairs from AI Studio will be imported as "llm_generated" with "pending review" status. Continue?'))) return;

                try {
                    const resp = await fetch(`/api/ai/eval/datasets/${selectedDatasetId}/import-synthetic-qa`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ job_id: jid, max_samples: 10 }),
                    });
                    const res = await resp.json();
                    if (!resp.ok) throw new Error(res.detail || 'Error importing synthetic QA');
                    showToast(res.message, 'success');
                    loadDatasetDetails(selectedDatasetId);
                } catch (err) {
                    showToast(err.message, 'danger');
                }
            });
        }

        // Add Manual Sample Modal
        const modalAddSample = document.getElementById('modal-add-sample');
        const btnOpenAddSample = document.getElementById('btn-open-add-sample-modal');
        const btnCloseAddSample = document.getElementById('btn-close-add-sample-modal');
        const btnDismissAddSample = document.getElementById('btn-dismiss-add-sample-modal');
        const btnConfirmAddSample = document.getElementById('btn-confirm-add-sample');

        if (btnOpenAddSample) btnOpenAddSample.addEventListener('click', () => modalAddSample?.classList.remove('hidden'));
        if (btnCloseAddSample) btnCloseAddSample.addEventListener('click', () => modalAddSample?.classList.add('hidden'));
        if (btnDismissAddSample) btnDismissAddSample.addEventListener('click', () => modalAddSample?.classList.add('hidden'));

        if (btnConfirmAddSample) {
            btnConfirmAddSample.addEventListener('click', async () => {
                if (!selectedDatasetId) return;
                const question = document.getElementById('new-sample-question')?.value?.trim();
                if (!question) {
                    showToast(t('eval_toast_enter_query', 'Query text cannot be empty.'), 'warning');
                    return;
                }
                const rawChunks = document.getElementById('new-sample-expected-chunks')?.value?.trim() || '';
                const rawUrls = document.getElementById('new-sample-expected-urls')?.value?.trim() || '';
                const origin = document.getElementById('new-sample-origin')?.value || 'manual';
                const notes = document.getElementById('new-sample-notes')?.value?.trim() || null;
                const humanReviewed = document.getElementById('new-sample-reviewed')?.checked || false;

                const expectedChunks = rawChunks ? rawChunks.split(',').map(s => s.trim()).filter(Boolean) : [];
                const expectedUrls = rawUrls ? rawUrls.split(',').map(s => s.trim()).filter(Boolean) : [];

                try {
                    const resp = await fetch(`/api/ai/eval/datasets/${selectedDatasetId}/samples`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            question,
                            job_id: resolveJobId(),
                            expected_chunk_ids: expectedChunks,
                            expected_source_urls: expectedUrls,
                            origin,
                            notes,
                            human_reviewed: humanReviewed,
                        }),
                    });
                    if (resp.ok) {
                        modalAddSample?.classList.add('hidden');
                        document.getElementById('new-sample-question').value = '';
                        document.getElementById('new-sample-expected-chunks').value = '';
                        document.getElementById('new-sample-expected-urls').value = '';
                        showToast(t('eval_modal_as_title', 'Sample added successfully.'), 'success');
                        loadDatasetDetails(selectedDatasetId);
                    }
                } catch (err) {
                    showToast(err.message, 'danger');
                }
            });
        }

        // Review Sample Modal
        const modalReviewSample = document.getElementById('modal-review-sample');
        const btnCloseReview = document.getElementById('btn-close-review-sample-modal');
        const btnDismissReview = document.getElementById('btn-dismiss-review-sample-modal');
        const btnConfirmSaveReview = document.getElementById('btn-confirm-save-review');

        if (btnCloseReview) btnCloseReview.addEventListener('click', () => modalReviewSample?.classList.add('hidden'));
        if (btnDismissReview) btnDismissReview.addEventListener('click', () => modalReviewSample?.classList.add('hidden'));

        function openReviewModal(sample) {
            if (!modalReviewSample) return;
            document.getElementById('review-sample-id').value = sample.sample_id;
            document.getElementById('review-sample-question-text').textContent = sample.question;
            document.getElementById('review-expected-chunks').value = (sample.expected_chunk_ids || []).join(', ');
            document.getElementById('review-expected-urls').value = (sample.expected_source_urls || []).join(', ');
            document.getElementById('review-graded-labels').value = JSON.stringify(sample.relevance_labels || {});
            document.getElementById('review-sample-notes').value = sample.notes || '';
            document.getElementById('review-human-verified').checked = !!sample.human_reviewed;

            modalReviewSample.classList.remove('hidden');
        }

        if (btnConfirmSaveReview) {
            btnConfirmSaveReview.addEventListener('click', async () => {
                const sampleId = document.getElementById('review-sample-id')?.value;
                if (!sampleId || !selectedDatasetId) return;

                const rawChunks = document.getElementById('review-expected-chunks')?.value?.trim() || '';
                const rawUrls = document.getElementById('review-expected-urls')?.value?.trim() || '';
                const rawLabels = document.getElementById('review-graded-labels')?.value?.trim() || '{}';
                const notes = document.getElementById('review-sample-notes')?.value?.trim() || null;
                const humanReviewed = document.getElementById('review-human-verified')?.checked || false;

                let gradedLabels = {};
                try {
                    gradedLabels = JSON.parse(rawLabels);
                } catch (_) {}

                const expectedChunks = rawChunks ? rawChunks.split(',').map(s => s.trim()).filter(Boolean) : [];
                const expectedUrls = rawUrls ? rawUrls.split(',').map(s => s.trim()).filter(Boolean) : [];

                try {
                    const resp = await fetch(`/api/ai/eval/datasets/${selectedDatasetId}/samples/${sampleId}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            expected_chunk_ids: expectedChunks,
                            expected_source_urls: expectedUrls,
                            relevance_labels: gradedLabels,
                            notes,
                            human_reviewed: humanReviewed,
                        }),
                    });
                    if (resp.ok) {
                        modalReviewSample?.classList.add('hidden');
                        showToast(t('eval_modal_rv_title', 'Review labels saved successfully.'), 'success');
                        loadDatasetDetails(selectedDatasetId);
                    }
                } catch (err) {
                    showToast(err.message, 'danger');
                }
            });
        }

        // --- Sub-panel 4: Runs & Metrics ---
        const btnExecuteEvalRun = document.getElementById('btn-execute-eval-run');
        if (btnExecuteEvalRun) {
            btnExecuteEvalRun.addEventListener('click', async () => {
                const datasetId = document.getElementById('run-dataset-select')?.value;
                if (!datasetId) {
                    showToast(t('eval_ds_select_lbl', 'No evaluation dataset selected.'), 'warning');
                    return;
                }
                const jid = resolveJobId();
                if (!jid) {
                    showToast(t('eval_job_placeholder', 'Invalid Job ID.'), 'warning');
                    return;
                }

                const method = document.getElementById('run-method-select')?.value || 'hybrid';
                const topK = parseInt(document.getElementById('run-topk-input')?.value || '5', 10);
                const alpha = parseFloat(document.getElementById('run-alpha-input')?.value || '0.7');

                const container = document.getElementById('eval-run-results-area');
                if (container) {
                    container.innerHTML = `<div class="empty-state"><i class="fa-solid fa-spinner fa-spin empty-icon"></i><p>${t('eval_run_running', 'Running benchmark and calculating retrieval metrics...')}</p></div>`;
                }

                try {
                    const resp = await fetch('/api/ai/eval/runs', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            dataset_id: datasetId,
                            job_id: jid,
                            method,
                            top_k: topK,
                            alpha,
                        }),
                    });
                    const res = await resp.json();
                    if (!resp.ok) throw new Error(res.detail || 'Error executing eval run');
                    lastRunData = res.data;
                    renderEvalRunResults(res.data, container);
                    refreshRunsDropdowns();
                } catch (err) {
                    if (container) {
                        container.innerHTML = `<div class="eval-alert-danger"><i class="fa-solid fa-triangle-exclamation"></i><span>${escapeHtml(err.message)}</span></div>`;
                    }
                }
            });
        }

        function renderEvalRunResults(run, container) {
            if (!container || !run) return;
            const m = run.aggregate_metrics || {};

            let alertBanner = '';
            if (run.insufficient_ground_truth) {
                alertBanner = `
                    <div class="eval-alert-danger">
                        <i class="fa-solid fa-triangle-exclamation" style="font-size:1.3rem;"></i>
                        <div>
                            <strong>${t('eval_run_err_insufficient_gt', 'Cannot calculate numeric metrics:')}</strong>
                            <p style="margin:0.25rem 0 0 0;">${escapeHtml(run.ground_truth_warning || t('eval_run_err_no_gt_desc', 'No human ground truth labels available for samples in this dataset.'))}</p>
                        </div>
                    </div>
                `;
            } else if (run.ground_truth_warning) {
                alertBanner = `
                    <div class="eval-alert-warning">
                        <i class="fa-solid fa-circle-exclamation" style="font-size:1.3rem;"></i>
                        <div>${escapeHtml(run.ground_truth_warning)}</div>
                    </div>
                `;
            }

            const metricCardsHtml = !run.insufficient_ground_truth ? `
                <div class="eval-metric-grid">
                    <div class="eval-metric-card">
                        <div class="eval-metric-val">${m[`recall_at_${run.config.top_k}`] ?? '-'}</div>
                        <div class="eval-metric-label">${t('eval_metric_recall', 'Recall@K')} (${run.config.top_k})</div>
                        <div class="eval-metric-req">${t('eval_metric_req_gt', 'Requires Ground Truth')}</div>
                    </div>
                    <div class="eval-metric-card">
                        <div class="eval-metric-val">${m[`precision_at_${run.config.top_k}`] ?? '-'}</div>
                        <div class="eval-metric-label">${t('eval_metric_precision', 'Precision@K')} (${run.config.top_k})</div>
                        <div class="eval-metric-req">${t('eval_metric_req_gt', 'Requires Ground Truth')}</div>
                    </div>
                    <div class="eval-metric-card">
                        <div class="eval-metric-val">${m['mrr'] ?? '-'}</div>
                        <div class="eval-metric-label">${t('eval_metric_mrr', 'MRR')}</div>
                        <div class="eval-metric-req">${t('eval_metric_req_mrr', 'Rank of first relevant item')}</div>
                    </div>
                    <div class="eval-metric-card">
                        <div class="eval-metric-val">${m['hit_rate'] ?? '-'}</div>
                        <div class="eval-metric-label">${t('eval_metric_hit', 'Hit Rate')}</div>
                        <div class="eval-metric-req">${t('eval_metric_req_hit', 'At least 1 relevant chunk in Top-K')}</div>
                    </div>
                    <div class="eval-metric-card">
                        <div class="eval-metric-val">${m[`ndcg_at_${run.config.top_k}`] ?? 'N/A'}</div>
                        <div class="eval-metric-label">${t('eval_metric_ndcg', 'nDCG@K')} (${run.config.top_k})</div>
                        <div class="eval-metric-req">${t('eval_metric_req_graded', 'Only with graded labels')}</div>
                    </div>
                </div>
            ` : '';

            const tableHtml = `
                <div class="eval-section-header" style="margin-top:1.25rem;">
                    <h4><i class="fa-solid fa-table-list text-primary"></i> ${t('eval_run_results_title', 'Per-Query Results')} (Run ID: <code dir="ltr">${run.run_id}</code>):</h4>
                </div>
                <div class="table-responsive" style="margin-top:0.5rem;">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th data-i18n="eval_th_question">${t('eval_th_question', 'Query')}</th>
                                <th data-i18n="eval_th_gt">${t('eval_th_gt', 'Ground Truth Status')}</th>
                                <th>Recall</th>
                                <th>Precision</th>
                                <th data-i18n="eval_th_first_rank">${t('eval_th_first_rank', 'First Hit Rank')}</th>
                                <th>MRR</th>
                                <th data-i18n="eval_th_hit">${t('eval_th_hit', 'Hit')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${run.sample_results.map(s => `
                                <tr>
                                    <td dir="auto"><strong>${escapeHtml(s.question)}</strong></td>
                                    <td>${s.has_ground_truth ? `<span class="badge badge-success">${t('eval_review_verified', 'Verified')}</span>` : `<span class="badge badge-danger">${t('eval_gt_none', 'No Label')}</span>`}</td>
                                    <td>${s.recall_at_k !== null ? s.recall_at_k : '-'}</td>
                                    <td>${s.precision_at_k !== null ? s.precision_at_k : '-'}</td>
                                    <td>${s.first_relevant_rank ? `#${s.first_relevant_rank}` : '-'}</td>
                                    <td>${s.mrr !== null ? s.mrr : '-'}</td>
                                    <td>${s.hit_rate !== null ? (s.hit_rate > 0 ? '✓' : '✗') : '-'}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            `;

            container.innerHTML = alertBanner + metricCardsHtml + tableHtml;
        }

        async function refreshRunsDropdowns() {
            try {
                const resp = await fetch('/api/ai/eval/runs');
                if (!resp.ok) return;
                const res = await resp.json();
                const runs = res.data || [];
                lastRunResults = runs;

                const selA = document.getElementById('diff-run-a-select');
                const selB = document.getElementById('diff-run-b-select');
                if (selA && selB) {
                    selA.innerHTML = '';
                    selB.innerHTML = '';
                    runs.forEach((r, idx) => {
                        const opt = document.createElement('option');
                        opt.value = r.run_id;
                        opt.textContent = `${r.run_id} (${r.dataset_name} - ${r.method.toUpperCase()} - Top ${r.top_k})`;
                        selA.appendChild(opt);
                        selB.appendChild(opt.cloneNode(true));
                    });
                    if (runs.length >= 2) {
                        selA.selectedIndex = 0;
                        selB.selectedIndex = 1;
                    }
                }
            } catch (_) {}
        }

        // --- Sub-panel 5: Version Diff ---
        const btnCompareRuns = document.getElementById('btn-execute-run-compare');
        if (btnCompareRuns) {
            btnCompareRuns.addEventListener('click', async () => {
                const runA = document.getElementById('diff-run-a-select')?.value;
                const runB = document.getElementById('diff-run-b-select')?.value;
                if (!runA || !runB) {
                    showToast(t('eval_diff_run_a', 'Please select both benchmark runs.'), 'warning');
                    return;
                }
                if (runA === runB) {
                    showToast(t('eval_toast_diff_distinct', 'Please select two distinct benchmark runs.'), 'warning');
                    return;
                }

                const container = document.getElementById('eval-diff-results-area');
                if (container) {
                    container.innerHTML = `<div class="empty-state"><i class="fa-solid fa-spinner fa-spin empty-icon"></i><p>${t('eval_diff_empty_desc', 'Calculating metric deltas...')}</p></div>`;
                }

                try {
                    const resp = await fetch('/api/ai/eval/runs/compare', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ run_id_a: runA, run_id_b: runB }),
                    });
                    const res = await resp.json();
                    if (!resp.ok) throw new Error(res.detail || 'Error comparing runs');
                    lastDiffData = res.data;
                    renderRunComparison(res.data, container);
                } catch (err) {
                    if (container) {
                        container.innerHTML = `<div class="eval-alert-danger"><i class="fa-solid fa-triangle-exclamation"></i><span>${escapeHtml(err.message)}</span></div>`;
                    }
                }
            });
        }

        function renderRunComparison(diff, container) {
            if (!container || !diff) return;
            const deltas = diff.metric_deltas || {};
            const formatDelta = (val) => {
                if (val === null || val === undefined) return '-';
                if (val > 0) return `<span style="color:#2ecc71; font-weight:700;" dir="ltr">+${val}</span>`;
                if (val < 0) return `<span style="color:#e74c3c; font-weight:700;" dir="ltr">${val}</span>`;
                return `<span style="color:var(--color-text-secondary);" dir="ltr">0.0000</span>`;
            };

            const deltasHtml = `
                <div class="diff-stat-chip-row">
                    ${Object.entries(deltas).map(([k, v]) => `
                        <div class="diff-chip">
                            <strong>${k}:</strong> ${formatDelta(v)}
                        </div>
                    `).join('')}
                </div>
                <div class="eval-notice-box" style="margin-top:0.75rem;">
                    <i class="fa-solid fa-circle-check text-primary"></i>
                    <span>${escapeHtml(diff.summary_message)}</span>
                </div>
            `;

            const renderTransitions = (title, items, borderClass, icon) => `
                <div style="margin-top:1rem;">
                    <h5 style="margin-bottom:0.5rem;"><i class="${icon}"></i> ${title} (${items.length}):</h5>
                    ${items.length === 0 ? `<div style="font-size:0.8rem; color:var(--color-text-secondary);">${t('eval_diff_no_items', 'No items in this category.')}</div>` : ''}
                    ${items.map(it => `
                        <div class="eval-result-card ${borderClass}" style="margin-bottom:0.4rem; padding:0.6rem;">
                            <div style="font-weight:600; font-size:0.85rem;" dir="auto">${escapeHtml(it.question)}</div>
                            <div style="font-size:0.78rem; color:var(--color-text-secondary); margin-top:0.25rem;">
                                ${t('eval_diff_rank_label', 'Rank:')} <code dir="ltr">#${it.run_a_first_rank ?? t('eval_diff_out_of_k', 'Out of K')}</code> ← <code dir="ltr">#${it.run_b_first_rank ?? t('eval_diff_out_of_k', 'Out of K')}</code> | 
                                ${t('eval_diff_recall_delta', 'Recall Delta:')} <strong>${formatDelta(it.recall_delta)}</strong>
                            </div>
                        </div>
                    `).join('')}
                </div>
            `;

            container.innerHTML = deltasHtml + `
                <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:1rem;">
                    ${renderTransitions(t('eval_diff_improved', 'Improved Queries'), diff.improved_queries, 'query-transition-improved', 'fa-solid fa-arrow-trend-up text-success')}
                    ${renderTransitions(t('eval_diff_regressed', 'Regressed Queries'), diff.regressed_queries, 'query-transition-regressed', 'fa-solid fa-arrow-trend-down text-danger')}
                </div>
            `;
        }

        // --- Sub-panel 6: Retrieval Debugger ---
        const btnRunRetrievalDebug = document.getElementById('btn-run-retrieval-debug');
        if (btnRunRetrievalDebug) {
            btnRunRetrievalDebug.addEventListener('click', async () => {
                const jid = resolveJobId();
                if (!jid) {
                    showToast(t('eval_job_placeholder', 'Invalid Job ID.'), 'warning');
                    return;
                }
                const query = document.getElementById('dbg-query-input')?.value?.trim();
                if (!query) {
                    showToast(t('eval_toast_enter_query', 'Please enter query text.'), 'warning');
                    return;
                }

                const container = document.getElementById('eval-dbg-results-area');
                if (container) {
                    container.innerHTML = `<div class="empty-state"><i class="fa-solid fa-spinner fa-spin empty-icon"></i><p>${t('eval_dbg_tracing', 'Tracing retrieval pipeline step-by-step...')}</p></div>`;
                }

                try {
                    const resp = await fetch('/api/ai/eval/playground/debug', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            job_id: jid,
                            query,
                            method: selectedMethod,
                            top_k: 5,
                            alpha: 0.7,
                            min_score: parseFloat(document.getElementById('pg-minscore-input')?.value || '0.0'),
                            category: document.getElementById('pg-filter-category')?.value?.trim() || null,
                            source_url: document.getElementById('pg-filter-url')?.value?.trim() || null,
                            expand_neighbors: document.getElementById('pg-expand-neighbors')?.checked || false,
                            version_label: document.getElementById('eval-version-select')?.value || null,
                        }),
                    });

                    const res = await resp.json();
                    if (!resp.ok) throw new Error(res.detail || 'Error in retrieval debugging');
                    lastTraceData = res.data;
                    renderDebugTrace(res.data, container);
                } catch (err) {
                    if (container) {
                        container.innerHTML = `<div class="eval-alert-danger"><i class="fa-solid fa-triangle-exclamation"></i><span>${escapeHtml(err.message)}</span></div>`;
                    }
                }
            });
        }

        function renderDebugTrace(trace, container) {
            if (!container || !trace) return;

            const warningsHtml = (trace.actionable_warnings && trace.actionable_warnings.length > 0) ? `
                <div class="eval-alert-warning" style="margin-bottom:1rem;">
                    <i class="fa-solid fa-bell"></i>
                    <div>
                        <strong>${t('eval_dbg_warn_title', 'System Diagnostic Warnings & Advisory:')}</strong>
                        <ul style="margin:0.25rem 0 0 1rem; padding:0;">
                            ${trace.actionable_warnings.map(w => `<li>${escapeHtml(w)}</li>`).join('')}
                        </ul>
                    </div>
                </div>
            ` : '';

            const step1 = `
                <div class="debug-trace-step">
                    <div class="debug-step-header">
                        <span><i class="fa-solid fa-spell-check text-primary"></i> ${t('eval_dbg_step1_title', 'Step 1: Query Analysis & Tokenization')}</span>
                        <span class="debug-step-badge info">${trace.detected_language}</span>
                    </div>
                    <div class="debug-step-body">
                        <div><strong>${t('eval_dbg_step1_norm', 'Normalized Query Text:')}</strong> <code>${escapeHtml(trace.query)}</code></div>
                        <div style="margin-top:0.4rem;"><strong>${t('eval_dbg_step1_tokens', 'Extracted Tokens:')}</strong> ${trace.tokens.map(t_token => `<span class="stage-pill" style="margin-inline-end:4px;">${escapeHtml(t_token)}</span>`).join('')}</div>
                    </div>
                </div>
            `;

            const step2 = `
                <div class="debug-trace-step">
                    <div class="debug-step-header">
                        <span><i class="fa-solid fa-filter text-primary"></i> ${t('eval_dbg_step2_title', 'Step 2: Metadata Filtering')}</span>
                        <span class="debug-step-badge ${trace.excluded_by_metadata > 0 ? 'warn' : 'pass'}">
                            ${t('eval_dbg_step2_excluded', 'Excluded:')} ${trace.excluded_by_metadata} | ${t('eval_dbg_step2_remaining', 'Remaining:')} ${trace.candidates_after_metadata_filter}
                        </span>
                    </div>
                    <div class="debug-step-body">
                        <div>${t('eval_dbg_step2_total', 'Total Initial Chunks in Dataset:')} <strong>${trace.total_chunks_in_dataset}</strong></div>
                        ${trace.metadata_exclusion_sample.length > 0 ? `
                            <div style="margin-top:0.5rem;">
                                <strong>${t('eval_dbg_step2_reasons', 'Sample reasons for chunk exclusion by metadata:')}</strong>
                                ${trace.metadata_exclusion_sample.map(e => `
                                    <div style="font-size:0.78rem; color:#f39c12; margin-top:2px;">
                                        • ${t('eval_pg_chunks_unit', 'chunks')} <code>${e.chunk_id}</code>: ${e.reasons.join(', ')}
                                    </div>
                                `).join('')}
                            </div>
                        ` : `<div style="color:#2ecc71; margin-top:0.3rem;">${t('eval_dbg_step2_none_excluded', '✓ No chunks were excluded by metadata filters.')}</div>`}
                    </div>
                </div>
            `;

            const step3 = `
                <div class="debug-trace-step">
                    <div class="debug-step-header">
                        <span><i class="fa-solid fa-calculator text-primary"></i> ${t('eval_dbg_step3_title', 'Step 3: Scoring & min_score Threshold Filtering')} (${trace.parameters.min_score})</span>
                        <span class="debug-step-badge ${trace.excluded_by_min_score > 0 ? 'warn' : 'pass'}">
                            ${t('eval_dbg_step3_excluded', 'Excluded due to low score:')} ${trace.excluded_by_min_score}
                        </span>
                    </div>
                    <div class="debug-step-body">
                        ${trace.min_score_exclusion_sample.length > 0 ? `
                            <div>
                                <strong>${t('eval_dbg_step3_sample', 'Sample chunks excluded due to score below threshold:')}</strong>
                                ${trace.min_score_exclusion_sample.map(e => `
                                    <div style="font-size:0.78rem; color:var(--color-text-secondary); margin-top:2px;">
                                        • ${t('eval_pg_chunks_unit', 'chunks')} <code>${e.chunk_id}</code>: ${t('eval_pg_score', 'score=')}${e.score} (${t('eval_pg_minscore_lbl', 'threshold=')}${e.min_score_threshold})
                                    </div>
                                `).join('')}
                            </div>
                        ` : `<div style="color:#2ecc71;">${t('eval_dbg_step3_all_passed', '✓ All candidates passed the score threshold.')}</div>`}
                    </div>
                </div>
            `;

            const step4 = `
                <div class="debug-trace-step">
                    <div class="debug-step-header">
                        <span><i class="fa-solid fa-arrows-split-up-and-left text-primary"></i> ${t('eval_dbg_step4_title', 'Step 4: Context Expansion Status')}</span>
                        <span class="debug-step-badge info">${trace.context_expansion_status.enabled ? t('eval_dbg_step4_enabled', 'Enabled') : t('eval_dbg_step4_disabled', 'Disabled')}</span>
                    </div>
                    <div class="debug-step-body">
                        <div>${t('eval_dbg_step4_attached', 'Attached neighbor chunks count:')} <strong>${trace.context_expansion_status.total_neighbor_chunks_attached}</strong> ${t('eval_pg_chunks_unit', 'chunks')}</div>
                    </div>
                </div>
            `;

            const step5 = `
                <div class="debug-trace-step">
                    <div class="debug-step-header">
                        <span><i class="fa-solid fa-list-ol text-primary"></i> ${t('eval_dbg_step5_title', 'Step 5: Final Ranked Output')} (${trace.final_results_count})</span>
                        <span class="debug-step-badge pass">${t('eval_dbg_step5_completed', 'Retrieval Completed')}</span>
                    </div>
                    <div class="debug-step-body">
                        ${trace.results.map(r => `
                            <div style="padding:0.4rem 0; border-bottom:1px solid #222; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem;">
                                <div>
                                    <span class="eval-rank-pill">#${r.rank}</span>
                                    <code style="margin-inline:6px;">${r.chunk_id}</code>
                                    <span style="font-size:0.8rem; color:var(--color-text-secondary);">${escapeHtml(r.text_preview.slice(0, 70))}...</span>
                                </div>
                                <span class="score-badge score-badge-${r.search_method}">${r.score}</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;

            container.innerHTML = warningsHtml + step1 + step2 + step3 + step4 + step5;
        }

        // Global Dynamic Re-renderer Hook for Language Toggle
        window.reRenderEvalStudio = function() {
            if (lastPlaygroundData) {
                renderPlaygroundResults(lastPlaygroundData, document.getElementById('pg-results-area'));
            }
            if (lastCompareData) {
                renderMethodComparison(lastCompareData, document.getElementById('cmp-results-area'));
            }
            if (lastDatasetDetails) {
                renderDatasetSummary(lastDatasetDetails);
                renderSamplesTable(lastDatasetDetails);
            }
            if (lastRunData) {
                renderEvalRunResults(lastRunData, document.getElementById('eval-run-results-area'));
            }
            if (lastDiffData) {
                renderRunComparison(lastDiffData, document.getElementById('eval-diff-results-area'));
            }
            if (lastTraceData) {
                renderDebugTrace(lastTraceData, document.getElementById('eval-dbg-results-area'));
            }
        };

        // Global Activation Hook for Eval Tab
        window.onEvalTabActivated = function() {
            loadAvailableJobs();
            loadEvalDatasets();
            refreshRunsDropdowns();
        };

        // Auto-run once on load
        setTimeout(() => {
            window.onEvalTabActivated();
        }, 150);
    }


