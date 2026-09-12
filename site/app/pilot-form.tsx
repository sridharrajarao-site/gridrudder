"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

export function PilotForm() {
  const [state, setState] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [message, setMessage] = useState("");
  const resultRef = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    if (state === "sent" || state === "error") resultRef.current?.focus();
  }, [state]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setState("sending");
    setMessage("");
    const form = event.currentTarget;
    const body = Object.fromEntries(new FormData(form));
    try {
      const response = await fetch("/api/pilot", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json() as { error?: string };
      if (!response.ok) throw new Error(result.error ?? "Submission failed");
      form.reset();
      setState("sent");
      setMessage("Request received. We’ll review the hardware fit and follow up by email.");
    } catch (error) {
      setState("error");
      setMessage(error instanceof Error ? error.message : "We couldn’t save the request. Please try again.");
    }
  }

  return (
    <form className="pilot-form" onSubmit={submit} aria-describedby="privacy-note">
      <div className="field-row"><label>Full name<input name="name" autoComplete="name" required maxLength={100} /></label><label>Work email<input name="email" type="email" autoComplete="email" required maxLength={254} /></label></div>
      <div className="field-row"><label>Organization<input name="organization" autoComplete="organization" required maxLength={160} /></label><label>GPU environment<select name="environment" required defaultValue=""><option value="" disabled>Select one</option><option>Single bare-metal server</option><option>Multi-GPU server</option><option>GPU cluster</option><option>Colocation environment</option><option>Other / evaluating</option></select></label></div>
      <label>What would you like to validate?<textarea name="goal" required maxLength={1200} rows={4} placeholder="Hardware, workload, power telemetry, and the outcome you need to measure." /></label>
      <label className="honeypot" aria-hidden="true">Company website<input name="website" tabIndex={-1} autoComplete="off" /></label>
      <label className="consent"><input name="consent" type="checkbox" value="yes" required /> <span>I agree that GridRudder may use these details to evaluate and respond to this pilot request.</span></label>
      <p id="privacy-note" className="form-note">Do not include credentials, IP addresses, or other secrets. Our monthly retention procedure removes requests older than 90 days; email pilot@gridrudder.com to request earlier deletion. See <a href="/privacy">privacy details</a>.</p>
      <button type="submit" disabled={state === "sending"}>{state === "sending" ? "Submitting…" : "Submit pilot request"}<span aria-hidden="true">→</span></button>
      <p ref={resultRef} className={`form-result ${state}`} role={state === "error" ? "alert" : state === "sent" ? "status" : undefined} aria-live="polite" tabIndex={-1}>{message}</p>
    </form>
  );
}
