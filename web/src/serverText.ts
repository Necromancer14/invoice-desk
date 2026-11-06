/**
 * Fixed English texts the server sends that the portal shows. Listing them with tk() lets
 * tools/check_i18n.mjs insist on an Arabic entry for each; views translate them with t(value).
 * Anything not listed here (a rule an admin named, a check's detail line) is shown as sent.
 * Keep in step with rules.py RULE_TYPES, providers.py PROVIDERS, samples.py LABELS,
 * default_rules.py and the trace step names in desk.py.
 */
import { tk } from "./i18n";

export const SERVER_TEXT = [
  // rule types: label, description, parameter names and help
  tk("Required fields"), tk("Every listed field must have a value."), tk("Field names"),
  tk("Field matches a pattern"), tk("A field must fully match a regular expression."),
  tk("VAT number format"), tk("15 digits, starting and ending with 3."),
  tk("VAT rate"), tk("VAT amount must equal the rate times the taxable amount. Zero-rated and exempt lines carry no VAT."),
  tk("Totals add up"), tk("Line items sum to the subtotal and subtotal plus VAT equals the total."),
  tk("Line arithmetic"), tk("Quantity times unit price equals each line total."),
  tk("Date is valid"), tk("A real date, optionally not in the future and not too old."),
  tk("Date order"), tk("The first date must not be after the second."),
  tk("Allowed currencies"), tk("Currency must be one of the listed codes."),
  tk("Amount limit"), tk("A numeric field must stay at or above a minimum and at or below a maximum."),
  tk("leave empty for no lower limit"), tk("leave empty for no upper limit"),
  tk("QR code agrees"), tk("The QR code's seller, VAT number, date, total and VAT must match the printed invoice."),
  tk("QR code present"), tk("The invoice should carry a QR code. With the option on, only simplified tax invoices are checked."), tk("simplified only"),
  tk("Duplicate invoice"), tk("The same seller VAT number and invoice number must not be received twice."),
  tk("Extraction confidence"), tk("Overall confidence of the extraction must reach a threshold."),
  tk("Custom expression"), tk("Write your own condition. It must be true for the invoice to pass."),
  tk("fields"), tk("field"), tk("pattern"), tk("optional"), tk("rate"), tk("tolerance"), tk("not future"), tk("max age days"),
  tk("first"), tk("second"), tk("allowed"), tk("min"), tk("max"), tk("required"), tk("threshold"), tk("expr"),

  // the default rule set's names (an admin can rename them; renamed rules show as typed)
  tk("Required fields present"), tk("Seller VAT number format"), tk("Buyer VAT number format"), tk("VAT is 15% of subtotal"),
  tk("Line quantity times price"), tk("Issue date is real and not in the future"), tk("Due date is not before issue date"),
  tk("Currency is SAR"), tk("Total above 50,000 needs a second look"), tk("QR code agrees with printed values"),
  tk("Not a duplicate"), tk("Extraction confidence is high enough"), tk("Total is not negative"),

  // AI providers
  tk("Ollama (on this computer)"),
  tk("Free key from Google AI Studio, no card needed. Reads images and PDFs. Google may use free-tier content to improve its products, so only use made-up invoices."),
  tk("Free plan with rate limits. Text and PDFs with a text layer only; images go to the review queue."),
  tk("Has models whose id ends in :free. Free model names change, so check openrouter.ai/models and paste one. Text and text-layer PDFs only."),
  tk("Runs a model on your own machine, no key and no cost. Only works when you run invoice-desk locally with INVOICE_DESK_ALLOW_LOCAL=1."),
  tk("Paid API key from the Anthropic Console. A Claude Pro chat subscription does not include API credits."),
  tk("Paid API key. Reads images; PDFs are read as text or as page images."),

  // sample scenarios
  tk("Clean invoice"), tk("Hidden instruction inside the invoice"), tk("Malformed seller VAT number"), tk("Wrong VAT rate"),
  tk("Totals do not add up"), tk("Issue date in the future"), tk("Duplicate of an earlier invoice"), tk("QR code disagrees with printed total"),
  tk("Foreign currency"), tk("High value invoice"), tk("Seller VAT number missing"), tk("Due date before issue date"),
  tk("VAT number in Arabic digits, grouped with spaces"), tk("Arabic-Indic digits and decimal separators"), tk("Zero-rated line, VAT on the rest only"), tk("Exempt line, VAT on the rest only"), tk("VAT charged on a zero-rated line"), tk("Hijri issue date"), tk("Hijri issue date in the future"), tk("No QR code on the invoice"), tk("Simplified tax invoice"),

  // AI connection test (api.py llm_test)
  tk("Connected and read the test invoice correctly."), tk("Connected, but the test invoice was not read as expected. Try another model."),

  // the built-in reader's name (AI readers are shown by their brand name)
  tk("rule-based"),

  // processing outcomes and notes (desk.py)
  tk("This PDF could not be opened. It may be damaged or not really a PDF."),
  tk("The AI call failed, so the built-in reader was used instead"), tk("No currency is printed, so SAR is assumed"),

  // processing trace steps
  tk("ingest"), tk("extract"), tk("qr"), tk("validate"), tk("route"), tk("human review"), tk("error"),
];
