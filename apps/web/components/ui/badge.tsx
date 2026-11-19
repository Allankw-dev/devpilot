import { cn } from "@/lib/utils";

const TONES = {
  neutral: "border-border text-muted-foreground",
  success: "border-success text-success",
  danger: "border-danger text-danger",
  warning: "border-warning text-warning",
  primary: "border-primary text-primary",
} as const;

export function Badge({
  tone = "neutral",
  className,
  children,
}: {
  tone?: keyof typeof TONES;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <span className={cn("inline-flex items-center rounded-full border px-2 py-0.5 text-[0.7rem]", TONES[tone], className)}>
      {children}
    </span>
  );
}
