"use client";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

export type Theme = "light" | "dark" | "system";
export const ACCENTS = [
  { id: "neutral", label: "Neutral", swatch: "#18181b" },
  { id: "blue", label: "Blue", swatch: "#2563eb" },
  { id: "violet", label: "Violet", swatch: "#7c3aed" },
  { id: "rose", label: "Rose", swatch: "#e11d48" },
  { id: "orange", label: "Orange", swatch: "#ea580c" },
  { id: "green", label: "Green", swatch: "#16a34a" },
  { id: "teal", label: "Teal", swatch: "#0d9488" },
] as const;

type Shell = {
  theme: Theme; setTheme: (t: Theme) => void;
  accent: string; setAccent: (a: string) => void;
  paletteOpen: boolean; setPaletteOpen: (v: boolean) => void;
  chatOpen: boolean; setChatOpen: (v: boolean) => void;
  chatSeed: string | null; askAgent: (q: string) => void;
  collapsed: boolean; setCollapsed: (v: boolean) => void;
  mobileNav: boolean; setMobileNav: (v: boolean) => void;
};
const Ctx = createContext<Shell | null>(null);

function read(key: string, fallback: string) {
  try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
}
function write(key: string, v: string) {
  try { localStorage.setItem(key, v); } catch {}
}

export function applyTheme(theme: Theme, accent: string) {
  const dark = theme === "system" ? matchMedia("(prefers-color-scheme: dark)").matches : theme === "dark";
  document.documentElement.classList.toggle("dark", dark);
  document.documentElement.dataset.accent = accent;
}

/** Inline script run before hydration to avoid a theme flash. */
export const THEME_BOOT = `(function(){try{var t=localStorage.getItem("ns:theme")||"system",a=localStorage.getItem("ns:accent")||"neutral";var d=t==="system"?matchMedia("(prefers-color-scheme: dark)").matches:t==="dark";document.documentElement.classList.toggle("dark",d);document.documentElement.dataset.accent=a}catch(e){}})()`;

export function ShellProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeS] = useState<Theme>("system");
  const [accent, setAccentS] = useState("neutral");
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatSeed, setChatSeed] = useState<string | null>(null);
  const [collapsed, setCollapsedS] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);

  useEffect(() => {
    setThemeS(read("ns:theme", "system") as Theme);
    setAccentS(read("ns:accent", "neutral"));
    setCollapsedS(read("ns:sidebar-collapsed", "0") === "1");
  }, []);

  const setTheme = useCallback((t: Theme) => { setThemeS(t); write("ns:theme", t); applyTheme(t, read("ns:accent", "neutral")); }, []);
  const setAccent = useCallback((a: string) => { setAccentS(a); write("ns:accent", a); applyTheme(read("ns:theme", "system") as Theme, a); }, []);
  const setCollapsed = useCallback((v: boolean) => { setCollapsedS(v); write("ns:sidebar-collapsed", v ? "1" : "0"); }, []);
  const askAgent = useCallback((q: string) => { setChatSeed(q + "\u0000" + Date.now()); setChatOpen(true); }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPaletteOpen((v) => !v); }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "j") { e.preventDefault(); setChatOpen((v) => !v); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <Ctx.Provider value={{ theme, setTheme, accent, setAccent, paletteOpen, setPaletteOpen, chatOpen, setChatOpen, chatSeed, askAgent, collapsed, setCollapsed, mobileNav, setMobileNav }}>
      {children}
    </Ctx.Provider>
  );
}

export function useShell() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useShell must be used inside <ShellProvider>");
  return v;
}
