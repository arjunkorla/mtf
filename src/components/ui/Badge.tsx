import { SignalQuality, SignalStrength } from "../../types/api";

interface BadgeProps {
  children: React.ReactNode;
  variant?: "default" | "positive" | "negative" | "warning" | "neutral" | "muted";
  size?: "sm" | "md";
}

export default function Badge({ children, variant = "default", size = "sm" }: BadgeProps) {
  const variants = {
    default: "bg-[#1A2540] text-[#94A3B8] border border-[#1E2840]",
    positive: "bg-[#0E2E2A] text-[#22C9B4] border border-[#164E48]",
    negative: "bg-[#2E1212] text-[#F05252] border border-[#4E1B1B]",
    warning: "bg-[#2E1F06] text-[#F59E0B] border border-[#4E3510]",
    neutral: "bg-[#1A2135] text-[#64748B] border border-[#1E2840]",
    muted: "bg-transparent text-[#64748B]",
  };

  const sizes = {
    sm: "text-[10px] px-2 py-0.5 tracking-wider",
    md: "text-xs px-2.5 py-1 tracking-wider",
  };

  return (
    <span
      className={`inline-flex items-center rounded font-heading font-semibold uppercase ${variants[variant]} ${sizes[size]}`}
    >
      {children}
    </span>
  );
}

export function SignalQualityBadge({ quality }: { quality: SignalQuality }) {
  const map: Record<SignalQuality, BadgeProps["variant"]> = {
    HIGH: "positive",
    MEDIUM: "warning",
    LOW: "negative",
  };
  return <Badge variant={map[quality]}>{quality}</Badge>;
}

export function StrengthBadge({ strength }: { strength: SignalStrength }) {
  const map: Record<SignalStrength, BadgeProps["variant"]> = {
    STRONG: "positive",
    MODERATE: "warning",
    WEAK: "negative",
    NEUTRAL: "neutral",
    INSUFFICIENT_DATA: "muted",
  };
  const labels: Record<SignalStrength, string> = {
    STRONG: "Strong",
    MODERATE: "Moderate",
    WEAK: "Weak",
    NEUTRAL: "Neutral",
    INSUFFICIENT_DATA: "Insufficient Data",
  };
  return <Badge variant={map[strength]}>{labels[strength]}</Badge>;
}
