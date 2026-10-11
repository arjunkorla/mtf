// Run with: npm test  (node --test, native TypeScript type stripping; no extra deps)
import { test } from "node:test";
import assert from "node:assert/strict";
import { FYERS_AUTH_REQUIRED, fyersIndicator, fyersLoginUrl, isFyersAuthRequired, type FyersStatus } from "./fyersAuthState.ts";

function status(code: FyersStatus["status"]): FyersStatus {
  return {
    mode: code === "MOCK" ? "mock" : "live",
    status: code,
    authenticated: code === "CONNECTED" || code === "MOCK",
    refresh_available: code === "REFRESH_REQUIRED",
    refresh_requires_pin: true,
    verified: false,
    last_verified_at: null,
    verification_error: null,
    access_expires_at: null,
    refresh_expires_at: null,
    token_source: "none",
    login_url: "/api/fyers/login",
    message: "",
  };
}

test("FYERS_AUTH_REQUIRED errors are recognised; other failures are not", () => {
  assert.equal(isFyersAuthRequired({ status: 401, code: FYERS_AUTH_REQUIRED, message: "x" }), true);
  assert.equal(isFyersAuthRequired({ status: 502, message: "FYERS API error on /history: HTTP 500" }), false);
  assert.equal(isFyersAuthRequired(new Error("boom")), false);
  assert.equal(isFyersAuthRequired(null), false);
});

test("login URL points at the backend login route", () => {
  assert.equal(fyersLoginUrl("http://127.0.0.1:8000/api"), "http://127.0.0.1:8000/api/fyers/login");
  assert.equal(fyersLoginUrl("http://localhost:8000/api/"), "http://localhost:8000/api/fyers/login");
});

test("indicator states", () => {
  assert.deepEqual(
    [fyersIndicator(status("CONNECTED")).connected, fyersIndicator(status("CONNECTED")).needsLogin],
    [true, false],
  );
  assert.equal(fyersIndicator(status("LOGIN_REQUIRED")).needsLogin, true);
  assert.equal(fyersIndicator(status("LOGIN_REQUIRED")).canRefreshWithPin, false);
  assert.equal(fyersIndicator(status("REFRESH_REQUIRED")).canRefreshWithPin, true);
  assert.equal(fyersIndicator(status("MOCK")).needsLogin, false);
  assert.equal(fyersIndicator(null).label, "Checking");
  assert.equal(fyersIndicator(null, true).needsLogin, false);
});

test("status payload type carries no token fields", () => {
  const keys = Object.keys(status("CONNECTED"));
  for (const forbidden of ["access_token", "refresh_token", "secret", "pin"]) {
    assert.equal(keys.includes(forbidden), false);
  }
});
