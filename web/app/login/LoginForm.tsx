"use client";

import Image from "next/image";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { ArrowRight, CheckCircle2, Loader2, LockKeyhole, ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";

type AuthStatus = "checking" | "ready" | "disabled" | "signed-out";

function safeNextPath(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) {
    return "/chat";
  }
  return value;
}

export default function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { t } = useTranslation();
  const nextPath = useMemo(() => safeNextPath(searchParams.get("next")), [searchParams]);
  const shouldLogout = searchParams.get("logout") === "1";
  const [status, setStatus] = useState<AuthStatus>("checking");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let active = true;

    async function refreshStatus() {
      if (shouldLogout) {
        await fetch("/api/auth/logout", { method: "POST" });
        if (active) setStatus("signed-out");
        return;
      }

      const response = await fetch("/api/auth/status", { cache: "no-store" });
      const data = (await response.json()) as {
        enabled?: boolean;
        configured?: boolean;
        authenticated?: boolean;
      };

      if (!active) return;
      if (!data.enabled || !data.configured) {
        setStatus("disabled");
        return;
      }
      if (data.authenticated) {
        router.replace(nextPath);
        return;
      }
      setStatus("ready");
    }

    void refreshStatus().catch(() => {
      if (active) setStatus("ready");
    });

    return () => {
      active = false;
    };
  }, [nextPath, router, shouldLogout]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");

    if (!password.trim()) {
      setError(t("Password is required"));
      return;
    }

    setSubmitting(true);
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });

      if (!response.ok) {
        setError(t("Incorrect password"));
        return;
      }

      router.replace(nextPath);
    } catch {
      setError(t("Login failed"));
    } finally {
      setSubmitting(false);
    }
  }

  const loading = status === "checking";
  const unlocked = status === "disabled" || status === "signed-out";

  return (
    <main className="min-h-screen overflow-y-auto bg-[var(--background)] text-[var(--foreground)]">
      <div className="mx-auto flex min-h-screen w-full max-w-6xl items-center px-5 py-8 sm:px-8">
        <section className="grid w-full overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-2xl shadow-black/10 md:grid-cols-[0.95fr_1.05fr]">
          <div className="relative hidden min-h-[560px] flex-col justify-between overflow-hidden bg-[#171615] p-10 text-white md:flex">
            <div className="absolute inset-0 opacity-35 [background-image:linear-gradient(rgba(255,255,255,.08)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,.08)_1px,transparent_1px)] [background-size:42px_42px]" />
            <div className="absolute inset-x-0 bottom-0 h-44 bg-[linear-gradient(180deg,transparent,rgba(176,80,30,.35))]" />

            <div className="relative z-10 flex items-center gap-3">
              <Image
                src="/logo-ver2.png"
                alt={t("DeepTutor")}
                width={34}
                height={34}
                className="h-[34px] w-[34px] rounded-lg"
                priority
              />
              <div>
                <div className="text-sm font-semibold">{t("DeepTutor")}</div>
                <div className="text-xs text-white/55">{t("Secure workspace")}</div>
              </div>
            </div>

            <div className="relative z-10 space-y-5">
              <div className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/10 px-3 py-1 text-xs text-white/75">
                <ShieldCheck size={14} />
                {t("Session verified")}
              </div>
              <div className="max-w-sm space-y-3">
                <h1 className="text-4xl font-semibold leading-tight tracking-normal">
                  {t("Access DeepTutor")}
                </h1>
                <p className="text-sm leading-6 text-white/62">
                  {t("Protected notes, agents, and knowledge tools.")}
                </p>
              </div>
            </div>
          </div>

          <div className="flex min-h-[560px] items-center justify-center px-5 py-10 sm:px-8">
            <div className="w-full max-w-[380px]">
              <div className="mb-8 flex items-center gap-3 md:hidden">
                <Image
                  src="/logo-ver2.png"
                  alt={t("DeepTutor")}
                  width={30}
                  height={30}
                  className="h-[30px] w-[30px] rounded-lg"
                  priority
                />
                <div className="text-sm font-semibold">{t("DeepTutor")}</div>
              </div>

              <div className="mb-7 space-y-2">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[var(--secondary)] text-[var(--primary)]">
                  {loading ? <Loader2 className="animate-spin" size={20} /> : <LockKeyhole size={20} />}
                </div>
                <h2 className="text-2xl font-semibold tracking-normal">
                  {loading ? t("Checking access...") : t("Sign in")}
                </h2>
                <p className="text-sm leading-6 text-[var(--muted-foreground)]">
                  {unlocked
                    ? status === "signed-out"
                      ? t("Sign out complete")
                      : t("Access control is not configured")
                    : t("Use the deployment password to continue.")}
                </p>
              </div>

              {unlocked ? (
                <button
                  type="button"
                  onClick={() => router.replace(nextPath)}
                  className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-[var(--primary)] px-4 text-sm font-medium text-[var(--primary-foreground)] shadow-sm transition-opacity hover:opacity-90"
                >
                  <CheckCircle2 size={17} />
                  {t("Continue to DeepTutor")}
                </button>
              ) : (
                <form className="space-y-4" onSubmit={handleSubmit}>
                  <label className="block space-y-2">
                    <span className="text-sm font-medium">{t("Password")}</span>
                    <input
                      type="password"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      autoComplete="current-password"
                      placeholder={t("Enter access password")}
                      className="h-11 w-full rounded-lg border border-[var(--input)] bg-[var(--background)] px-3 text-sm outline-none transition focus:border-[var(--ring)] focus:ring-2 focus:ring-[var(--ring)]/20"
                      disabled={loading || submitting}
                    />
                  </label>

                  {error && (
                    <div className="rounded-lg border border-[var(--destructive)]/25 bg-[var(--destructive)]/10 px-3 py-2 text-sm text-[var(--destructive)]">
                      {error}
                    </div>
                  )}

                  <button
                    type="submit"
                    disabled={loading || submitting}
                    className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-[var(--primary)] px-4 text-sm font-medium text-[var(--primary-foreground)] shadow-sm transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {submitting ? (
                      <Loader2 className="animate-spin" size={17} />
                    ) : (
                      <ArrowRight size={17} />
                    )}
                    {submitting ? t("Signing in...") : t("Continue")}
                  </button>
                </form>
              )}
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
