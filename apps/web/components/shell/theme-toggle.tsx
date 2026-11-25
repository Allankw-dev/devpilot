"use client";

import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { applyTheme, type Theme } from "@/lib/theme";
import { useTheme } from "@/lib/use-theme";

export function ThemeToggle() {
  const theme = useTheme();

  const next: Theme = theme === "dark" ? "light" : "dark";
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={`Switch to ${next} theme`}
      onClick={() => applyTheme(next)}
    >
      {theme === "dark" ? <Sun className="h-4 w-4" aria-hidden /> : <Moon className="h-4 w-4" aria-hidden />}
    </Button>
  );
}
