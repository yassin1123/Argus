-- Phase 3 / Week 10 / Day 2: firm branding for export artifacts.
-- Shape: { logo_url, primary_color, secondary_color, font_family, footer_text }.
-- The exporter base accepts the branding dict by-value, so missing keys
-- fall through to defaults rather than failing the render.

ALTER TABLE firms
    ADD COLUMN IF NOT EXISTS branding JSONB DEFAULT '{}'::jsonb;

-- Backfill the demo firm so the rest of W10 has something to render with.
UPDATE firms
SET branding = jsonb_build_object(
    'logo_url',       '',
    'primary_color',  '#0F6E56',
    'secondary_color','#1B1F23',
    'font_family',    'Inter, -apple-system, sans-serif',
    'footer_text',    'Argus Demo Boutique · Confidential'
)
WHERE slug = 'argus-demo-boutique'
  AND (branding IS NULL OR branding = '{}'::jsonb);
