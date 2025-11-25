import 'package:flutter/material.dart';
import 'package:flutter/services.dart'; // من أجل النسخ للحافظة
import 'package:google_generative_ai/google_generative_ai.dart';
import 'package:animate_do/animate_do.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';

class AIRoadmapScreen extends StatefulWidget {
  @override
  _AIRoadmapScreenState createState() => _AIRoadmapScreenState();
}

class _AIRoadmapScreenState extends State<AIRoadmapScreen> {
  final _goalController = TextEditingController();
  final _durationController = TextEditingController();
  
  // --- إعدادات جديدة ---
  String _selectedLevel = 'مبتدئ';
  String _selectedLanguage = 'العربية';
  
  bool _isLoading = false;
  bool _isSaving = false;
  String? _roadmapResult;
  
  // مفتاح API (تأكد من حمايته في الإنتاج)
  final String apiKey = 'AIzaSyAP5WCqlWMylEUAjrCG8tn7KRE1kQd4mwE';

  // --- اقتراحات سريعة ---
  final List<Map<String, String>> _suggestions = [
    {'goal': 'تطوير تطبيقات Flutter', 'duration': '4 أسابيع'},
    {'goal': 'تعلم بايثون للذكاء الاصطناعي', 'duration': '3 أشهر'},
    {'goal': 'أساسيات الأمن السيبراني', 'duration': '6 أسابيع'},
    {'goal': 'تصميم واجهات المستخدم (UI/UX)', 'duration': 'شهرين'},
  ];

  void _fillSuggestion(Map<String, String> suggestion) {
    _goalController.text = suggestion['goal']!;
    _durationController.text = suggestion['duration']!;
  }

  Future<void> _generateRoadmap() async {
    if (_goalController.text.isEmpty || _durationController.text.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("يرجى ملء جميع الحقول")));
      return;
    }
    
    setState(() { _isLoading = true; _roadmapResult = null; });
    
    try {
      final model = GenerativeModel(model: 'gemini-1.5-pro', apiKey: apiKey);
      
      // برومبت محسن يقبل المتغيرات الجديدة
      final prompt = """
        بصفتك مستشاراً تعليمياً خبيراً، أنشئ خطة دراسية مفصلة (Roadmap) بناءً على التالي:
        - الموضوع: ${_goalController.text}
        - المدة المتاحة: ${_durationController.text}
        - المستوى الحالي للطالب: $_selectedLevel
        - لغة الخرج: $_selectedLanguage
        
        المطلوب:
        1. قسّم الخطة إلى أسابيع أو مراحل منطقية.
        2. لكل مرحلة، حدد المواضيع الفرعية والمصادر المقترحة (كتب، دورات، توثيق رسمي).
        3. أضف نصائح عملية للمذاكرة.
        4. استخدم تنسيق Markdown لتنظيم العناوين والنقاط بشكل جميل.
      """;
      
      final response = await model.generateContent([Content.text(prompt)]);
      setState(() => _roadmapResult = response.text);
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("حدث خطأ في الاتصال، حاول مجدداً.")));
    } finally {
      setState(() => _isLoading = false);
    }
  }

  // --- حفظ الخطة ---
  Future<void> _saveRoadmap() async {
    if (_roadmapResult == null) return;
    setState(() => _isSaving = true);
    
    final user = FirebaseAuth.instance.currentUser;
    if (user != null) {
      try {
        await FirebaseFirestore.instance.collection('users').doc(user.uid).collection('saved_roadmaps').add({
          'goal': _goalController.text,
          'duration': _durationController.text,
          'level': _selectedLevel,
          'content': _roadmapResult,
          'created_at': FieldValue.serverTimestamp(),
        });
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("تم حفظ الخطة بنجاح ✅"), backgroundColor: Colors.green));
      } catch (e) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("فشل الحفظ ❌"), backgroundColor: Colors.red));
      }
    }
    setState(() => _isSaving = false);
  }

  // --- نسخ للحافظة ---
  void _copyToClipboard() {
    if (_roadmapResult != null) {
      Clipboard.setData(ClipboardData(text: _roadmapResult!));
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("تم نسخ النص للحافظة 📋")));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text("مخطط المسار الذكي"),
        actions: [
          if (_roadmapResult != null) ...[
            IconButton(icon: Icon(Icons.copy), onPressed: _copyToClipboard, tooltip: "نسخ"),
            IconButton(
              icon: _isSaving 
                ? SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black)) 
                : Icon(Icons.save_alt),
              onPressed: _isSaving ? null : _saveRoadmap,
              tooltip: "حفظ",
            ),
          ]
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(20.0),
        child: Column(
          children: [
            // --- قسم الإدخال (يختفي عند ظهور النتيجة لتوفير المساحة أو يبقى، حسب التفضيل. هنا سأبقيه لكن يمكن طيه) ---
            if (_roadmapResult == null) 
            FadeInDown(
              child: Card(
                elevation: 0,
                color: Colors.grey[50],
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20), side: BorderSide(color: Colors.grey[200]!)),
                child: Padding(
                  padding: const EdgeInsets.all(20.0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text("🎯 اصنع خطتك بنفسك", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 18, color: Color(0xFF6C63FF))),
                      SizedBox(height: 15),
                      
                      // حقول الإدخال
                      TextField(
                        controller: _goalController,
                        decoration: InputDecoration(
                          labelText: "ماذا تريد أن تتعلم؟",
                          hintText: "مثال: تطوير تطبيقات Flutter",
                          prefixIcon: Icon(Icons.school_outlined, color: Color(0xFF6C63FF)),
                          border: OutlineInputBorder(borderRadius: BorderRadius.circular(15)),
                          filled: true, fillColor: Colors.white
                        ),
                      ),
                      SizedBox(height: 15),
                      TextField(
                        controller: _durationController,
                        decoration: InputDecoration(
                          labelText: "المدة المتاحة",
                          hintText: "مثال: 4 أسابيع",
                          prefixIcon: Icon(Icons.timer_outlined, color: Color(0xFF6C63FF)),
                          border: OutlineInputBorder(borderRadius: BorderRadius.circular(15)),
                          filled: true, fillColor: Colors.white
                        ),
                      ),
                      
                      SizedBox(height: 15),
                      // خيارات التخصيص
                      Row(
                        children: [
                          Expanded(
                            child: DropdownButtonFormField<String>(
                              value: _selectedLevel,
                              decoration: InputDecoration(contentPadding: EdgeInsets.symmetric(horizontal: 10), border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)), filled: true, fillColor: Colors.white),
                              items: ['مبتدئ', 'متوسط', 'خبير'].map((e) => DropdownMenuItem(value: e, child: Text(e))).toList(),
                              onChanged: (v) => setState(() => _selectedLevel = v!),
                            ),
                          ),
                          SizedBox(width: 10),
                          Expanded(
                            child: DropdownButtonFormField<String>(
                              value: _selectedLanguage,
                              decoration: InputDecoration(contentPadding: EdgeInsets.symmetric(horizontal: 10), border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)), filled: true, fillColor: Colors.white),
                              items: ['العربية', 'English'].map((e) => DropdownMenuItem(value: e, child: Text(e))).toList(),
                              onChanged: (v) => setState(() => _selectedLanguage = v!),
                            ),
                          ),
                        ],
                      ),

                      SizedBox(height: 15),
                      Text("اقتراحات سريعة:", style: TextStyle(fontSize: 12, color: Colors.grey[600], fontWeight: FontWeight.bold)),
                      SizedBox(height: 8),
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: _suggestions.map((s) => ActionChip(
                          label: Text(s['goal']!, style: TextStyle(fontSize: 11)),
                          backgroundColor: Colors.white,
                          elevation: 1,
                          onPressed: () => _fillSuggestion(s),
                          avatar: Icon(Icons.bolt, size: 14, color: Colors.amber),
                        )).toList(),
                      ),

                      SizedBox(height: 20),
                      SizedBox(
                        width: double.infinity,
                        height: 50,
                        child: ElevatedButton.icon(
                          onPressed: _isLoading ? null : _generateRoadmap,
                          icon: _isLoading ? SizedBox() : Icon(Icons.auto_awesome),
                          label: _isLoading 
                            ? SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                            : Text("إنشاء الخطة الآن"),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: Color(0xFF6C63FF),
                            foregroundColor: Colors.white,
                            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(15))
                          ),
                        ),
                      )
                    ],
                  ),
                ),
              ),
            ),
            
            SizedBox(height: 20),
            
            // --- قسم النتائج ---
            Expanded(
              child: _roadmapResult == null 
              ? (_isLoading ? Center(child: Text("جاري إعداد خطة مخصصة لك...", style: TextStyle(color: Color(0xFF6C63FF)))) : Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.map_outlined, size: 80, color: Colors.grey[200]),
                      Text("املأ البيانات أعلاه لتبدأ رحلتك", style: TextStyle(color: Colors.grey))
                    ],
                  )))
              : FadeInUp(
                  child: Container(
                    padding: EdgeInsets.all(15),
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(15),
                      border: Border.all(color: Colors.grey.withOpacity(0.2)),
                      boxShadow: [BoxShadow(color: Colors.black12, blurRadius: 10)]
                    ),
                    child: Column(
                      children: [
                        // زر لإعادة المحاولة أو العودة
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Text("الخطة المقترحة", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                            TextButton.icon(
                              onPressed: () => setState(() => _roadmapResult = null), 
                              icon: Icon(Icons.refresh, size: 16),
                              label: Text("خطة جديدة")
                            )
                          ],
                        ),
                        Divider(),
                        Expanded(
                          child: Markdown(
                            data: _roadmapResult!,
                            styleSheet: MarkdownStyleSheet(
                              h1: TextStyle(color: Color(0xFF6C63FF), fontWeight: FontWeight.bold),
                              h2: TextStyle(color: Colors.black87, fontWeight: FontWeight.bold),
                              p: TextStyle(fontSize: 15, height: 1.5),
                              listBullet: TextStyle(color: Color(0xFF6C63FF)),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
            )
          ],
        ),
      ),
    );
  }
}