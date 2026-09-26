# التحقق من ملفات FHIR بالمدقّق الرسمي بتاع HL7

أداة للمطوّر بس. **مش جزء من البرنامج، ومش بتدخل أي عيادة، ومش بتشتغل على CI**:
محتاجة Java، وحوالي ١٥٠ ميجا مكتبات، و٣٠٠ ميجا تعريفات. اختبارات CI بتتأكد من نفس
القواعد بـ `fhir.resources` وبقواعد IPS مكتوبة واحدة واحدة في
`tests/test_the_summary_that_travels.py`.

## التشغيل

```bash
cd tools/fhir_validate
mvn -q dependency:copy-dependencies -DoutputDirectory=lib   # المدقّق ومكتباته
python fetch_packages.py                                    # تعريفات R4 و IPS
javac -cp "lib/*" FhirCheck.java

# ملخص IPS، مقابل بروفايل IPS:
java -Xmx6g -cp "lib/*:." FhirCheck \
    http://hl7.org/fhir/uv/ips/StructureDefinition/Bundle-uv-ips P1-ips.json
# الملف الكامل، مقابل FHIR R4 الأساسي:
java -Xmx6g -cp "lib/*:." FhirCheck - P1-fhir.json
```

## قراية النتيجة

المدقّق بيشتغل **من غير خادم مصطلحات**، لأن `tx.fhir.org` ممكن يبقى مش متاح.
فيه نوعين من الرسائل سببهم ده، وملهمش علاقة بالملف:

- **تحذيرات** «could not be found, so the code cannot be validated» و«running without
  terminology services»: الأكواد ما اتراجعتش على قاموسها.
- **أخطاء** «Element matches more than one slice - observation-pregnancy-edd, …»
  على أي `Observation`:
  - المدقّق مش قادر يتأكد إن كود الهيموجلوبين مثلاً مش كود حمل، فبيحسبه ممكن يطابق
    بروفايلات الحمل.
  - **أمثلة HL7 الرسمية نفسها** في حزمة IPS بتطلّع نفس الأخطاء دي بالظبط في الوضع ده
    (`Bundle-IPS-examples-Bundle-01.json`: ١٢ خطأ).

أي خطأ **غير** دول، خطأ حقيقي.
