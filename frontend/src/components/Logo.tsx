import { BRAND_NAME, LOGO_URL } from "@/lib/brand";

export function Logo({ className = "h-8 w-auto" }: { className?: string }) {
  return (
    <span
      role="img"
      aria-label={BRAND_NAME}
      className={`inline-flex items-center gap-1.5 whitespace-nowrap ${className}`}
    >
      <img
        src={LOGO_URL}
        alt=""
        aria-hidden="true"
        className="h-full w-auto object-contain"
      />
      <span>Reports</span>
    </span>
  );
}
