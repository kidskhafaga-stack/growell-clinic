import java.nio.file.*;
import java.util.*;
import org.hl7.fhir.validation.ValidationEngine;
import org.hl7.fhir.r5.elementmodel.Manager.FhirFormat;
import org.hl7.fhir.r5.model.OperationOutcome;
import org.hl7.fhir.utilities.validation.ValidationMessage;

/**
 * Validate FHIR JSON files offline with HL7's own validator, against a
 * profile ("-" for base R4). Args: profile file...
 * Loads R4 core and the IPS 2.0.0 package from ~/.fhir/packages (see
 * fetch_packages.py) and runs with no terminology server.
 */
public class FhirCheck {
  public static void main(String[] args) throws Exception {
    ValidationEngine engine = new ValidationEngine.ValidationEngineBuilder()
        .withVersion("4.0.1").withNoTerminologyServer()
        .withCanRunWithoutTerminologyServer(true)
        .fromSource("hl7.fhir.r4.core#4.0.1");
    engine.loadPackage("hl7.fhir.uv.ips", "2.0.0");
    String profile = args[0];
    int worst = 0;
    for (int i = 1; i < args.length; i++) {
      byte[] data = Files.readAllBytes(Paths.get(args[i]));
      List<ValidationMessage> msgs = new ArrayList<>();
      OperationOutcome oo = engine.validate(data, FhirFormat.JSON,
          profile.equals("-") ? List.of() : List.of(profile), msgs);
      int e = 0, w = 0;
      for (OperationOutcome.OperationOutcomeIssueComponent iss : oo.getIssue()) {
        String sev = iss.getSeverity().toCode();
        if (sev.equals("error") || sev.equals("fatal")) e++;
        if (sev.equals("warning")) w++;
        String loc = iss.getExpression().isEmpty() ? "" : iss.getExpression().get(0).getValue();
        System.out.println("  [" + sev + "] " + loc + " :: " + iss.getDetails().getText());
      }
      System.out.println("== " + args[i] + " errors=" + e + " warnings=" + w);
      if (e > 0) worst = 1;
    }
    System.exit(worst);
  }
}
