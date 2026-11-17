/** Plain-language names for the codes the usage page shows. Unknown ones are shown as they are. */

const FEATURES: Record<string, string> = {
  ask_retrieval: "Ask (finding code)",
  code_search: "Code search",
  indexing: "Indexing",
  review: "Pull request review",
  ci: "CI analysis",
  ai_test: "Connection test",
};

const ERRORS: Record<string, string> = {
  quota_exhausted: "Daily quota used up",
  rate_limited: "Rate limited (too many requests)",
  unavailable: "Provider unavailable or overloaded",
  timeout: "Provider timed out",
  auth: "API key rejected",
  bad_request: "Request rejected (check the model name)",
  blocked: "Blocked by the provider's safety filter",
  invalid_output: "Unusable answer from the model",
  not_configured: "AI not configured",
  not_supported: "Not supported by this provider",
  tool_loop: "Too many tool steps",
  unexpected: "Unexpected error",
  unknown: "Unknown",
};

export const featureLabel = (feature: string): string => FEATURES[feature] ?? feature;
export const errorLabel = (code: string): string => ERRORS[code] ?? code;
