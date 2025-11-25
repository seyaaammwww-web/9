import 'package:flutter/material.dart';
import 'package:flutter/services.dart'; // لاستخدام الحافظة (Clipboard)
import 'package:google_generative_ai/google_generative_ai.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:google_fonts/google_fonts.dart'; 
import 'package:animate_do/animate_do.dart';

class CodingLabTab extends StatefulWidget {
  @override
  _CodingLabTabState createState() => _CodingLabTabState();
}

class _CodingLabTabState extends State<CodingLabTab> {
  final TextEditingController _codeController = TextEditingController();
  final ScrollController _outputScrollController = ScrollController(); // للتحكم في التمرير
  
  String _output = "اكتب الكود واضغط تشغيل لرؤية النتائج...";
  bool _isRunning = false;
  String _selectedLanguage = "Python";
  double _fontSize = 14.0;
  
  final String apiKey = 'AIzaSyAP5WCqlWMylEUAjrCG8tn7KRE1kQd4mwE';

  Future<void> _runAndEvaluate() async {
    // 1. التحقق من الفراغ
    if (_codeController.text.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("يرجى كتابة كود أولاً!"), backgroundColor: Colors.orange));
      return;
    }

    setState(() { _isRunning = true; _output = "جاري تحليل الكود..."; });
    
    try {
      final model = GenerativeModel(model: 'gemini-2.5-pro', apiKey: apiKey);
      final prompt = "Act as a code compiler. Language: $_selectedLanguage. Code:\n${_codeController.text}\nOutput the result of execution, then give a rating /10 and brief advice.";
      final response = await model.generateContent([Content.text(prompt)]);
      
      setState(() { 
        _output = response.text ?? "لا توجد نتيجة"; 
      });

      // 2. التمرير التلقائي للأسفل عند وصول الرد
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_outputScrollController.hasClients) {
          _outputScrollController.animateTo(
            _outputScrollController.position.maxScrollExtent,
            duration: Duration(milliseconds: 500),
            curve: Curves.easeOut,
          );
        }
      });

    } catch (e) {
      setState(() { _output = "خطأ في الاتصال: $e"; });
    } finally {
      setState(() { _isRunning = false; });
    }
  }

  // دالة نسخ النتائج
  void _copyOutput() {
    Clipboard.setData(ClipboardData(text: _output));
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("تم نسخ النتائج للحافظة")));
  }

  // دالة مسح المحرر
  void _clearEditor() {
    _codeController.clear();
    setState(() { _output = "اكتب الكود واضغط تشغيل لرؤية النتائج..."; });
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final textColor = isDark ? Colors.white : Colors.black87;
    final cardColor = Theme.of(context).cardColor;

    return Padding(
      padding: EdgeInsets.fromLTRB(20, 50, 20, 160), // مسافة سفلية لمنع التداخل
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // رأس الصفحة والأدوات
          FadeInDown(child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text("المحرر الذكي", style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold, color: Color(0xFF6C63FF))),
              Row(
                children: [
                  IconButton(
                    icon: Icon(Icons.cleaning_services_rounded, color: Colors.redAccent),
                    tooltip: "مسح الكل",
                    onPressed: _clearEditor,
                  ),
                  IconButton(
                    icon: Icon(Icons.format_size, color: Colors.grey),
                    tooltip: "تغيير حجم الخط",
                    onPressed: () => setState(() => _fontSize = _fontSize == 14 ? 18 : 14),
                  ),
                ],
              )
            ],
          )),
          
          SizedBox(height: 15),
          
          // شريط التحكم (اللغة والتشغيل)
          Row(
            children: [
              Container(
                padding: EdgeInsets.symmetric(horizontal: 12),
                decoration: BoxDecoration(color: cardColor, borderRadius: BorderRadius.circular(10)),
                child: DropdownButton<String>(
                  value: _selectedLanguage,
                  underline: SizedBox(),
                  dropdownColor: cardColor,
                  style: TextStyle(color: textColor, fontWeight: FontWeight.bold),
                  items: ["Python", "Dart", "JavaScript", "C++"].map((e) => DropdownMenuItem(value: e, child: Text(e))).toList(),
                  onChanged: (v) => setState(() => _selectedLanguage = v!),
                ),
              ),
              Spacer(),
              ElevatedButton.icon(
                onPressed: _isRunning ? null : _runAndEvaluate,
                icon: _isRunning 
                  ? SizedBox(width: 15, height: 15, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2)) 
                  : Icon(Icons.play_arrow_rounded),
                label: Text("تشغيل"),
                style: ElevatedButton.styleFrom(backgroundColor: Colors.green, foregroundColor: Colors.white),
              )
            ],
          ),
          
          SizedBox(height: 15),

          // منطقة المحرر (Editor)
          Expanded(
            flex: 3,
            child: Container(
              decoration: BoxDecoration(
                color: Color(0xFF1E1E1E), // لون داكن ثابت للمحرر
                borderRadius: BorderRadius.circular(15),
                boxShadow: [BoxShadow(color: Colors.black26, blurRadius: 10)]
              ),
              child: Column(
                children: [
                  // شريط العنوان للمحرر
                  Container(
                    height: 30,
                    decoration: BoxDecoration(color: Color(0xFF252526), borderRadius: BorderRadius.vertical(top: Radius.circular(15))),
                    padding: EdgeInsets.symmetric(horizontal: 10),
                    child: Row(
                      children: [
                        Icon(Icons.circle, color: Colors.red, size: 10), SizedBox(width: 5), 
                        Icon(Icons.circle, color: Colors.amber, size: 10), SizedBox(width: 5), 
                        Icon(Icons.circle, color: Colors.green, size: 10),
                        Spacer(),
                        Text("Code Editor", style: TextStyle(color: Colors.grey, fontSize: 10)),
                        Spacer(),
                      ],
                    ),
                  ),
                  Expanded(
                    child: TextField(
                      controller: _codeController,
                      maxLines: null, 
                      expands: true,
                      style: GoogleFonts.firaCode(color: Colors.white, fontSize: _fontSize),
                      cursorColor: Colors.blueAccent,
                      decoration: InputDecoration(
                        hintText: "// اكتب الكود هنا...",
                        hintStyle: TextStyle(color: Colors.grey[600]),
                        border: InputBorder.none,
                        contentPadding: EdgeInsets.all(15)
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          
          SizedBox(height: 15),
          
          // شريط المخرجات وزر النسخ
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text("المخرجات:", style: TextStyle(fontWeight: FontWeight.bold, color: Colors.grey)),
              InkWell(
                onTap: _copyOutput,
                child: Row(
                  children: [
                    Icon(Icons.copy_rounded, size: 14, color: Colors.grey),
                    SizedBox(width: 4),
                    Text("نسخ النتيجة", style: TextStyle(color: Colors.grey, fontSize: 12)),
                  ],
                ),
              )
            ],
          ),
          
          SizedBox(height: 5),
          
          // منطقة عرض النتائج (Output)
          Expanded(
            flex: 2,
            child: Container(
              width: double.infinity,
              padding: EdgeInsets.all(15),
              decoration: BoxDecoration(
                color: isDark ? Color(0xFF252526) : Colors.white,
                borderRadius: BorderRadius.circular(15),
                border: Border.all(color: Colors.grey.withOpacity(0.2))
              ),
              child: SingleChildScrollView(
                controller: _outputScrollController, // ربط المتحكم بالتمرير
                child: MarkdownBody(
                  data: _output,
                  styleSheet: MarkdownStyleSheet(
                    p: TextStyle(color: textColor),
                    code: TextStyle(color: Colors.white, backgroundColor: Colors.black54),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}