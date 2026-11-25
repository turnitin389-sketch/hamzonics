import { BRAND_NAME, LOGO_URL } from "@/lib/brand";

export function Logo({ className = "h-8 w-auto" }: { className?: string }) {
  return (
    <img
      src={LOGO_URL}
      alt={BRAND_NAME}
      className={`object-contain ${className}`}
    />
  );
}
