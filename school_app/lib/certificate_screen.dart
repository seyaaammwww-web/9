import 'dart:typed_data';
import 'dart:math';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;
import 'package:printing/printing.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:intl/intl.dart';

class CertificateScreen extends StatefulWidget {
  final String courseName;
  const CertificateScreen({Key? key, required this.courseName}) : super(key: key);

  @override
  _CertificateScreenState createState() => _CertificateScreenState();
}

class _CertificateScreenState extends State<CertificateScreen> {
  String _studentName = "جاري التحميل...";
  String _certificateId = "";
  bool _isLoadingData = true;

  @override
  void initState() {
    super.initState();
    _loadUserData();
    _generateCertificateId();
  }

  void _generateCertificateId() {
    final timestamp = DateTime.now().millisecondsSinceEpoch.toString().substring(8);
    final random = Random().nextInt(9999).toString().padLeft(4, '0');
    setState(() {
      _certificateId = "CERT-$timestamp-$random";
    });
  }

  Future<void> _loadUserData() async {
    final user = FirebaseAuth.instance.currentUser;
    if (user != null) {
      var doc = await FirebaseFirestore.instance.collection('users').doc(user.uid).get();
      if (doc.exists && doc.data() != null) {
        setState(() {
          _studentName = doc.data()!['name'] ?? "طالب مجتهد";
          _isLoadingData = false;
        });
      }
    } else {
      setState(() => _isLoadingData = false);
    }
  }

  Future<Uint8List> _generatePdf(PdfPageFormat format) async {
    final pdf = pw.Document();
    
    // تحميل الخط
    final fontData = await rootBundle.load('assets/fonts/Cairo-Bold.ttf'); 
    final ttf = pw.Font.ttf(fontData);
    
    // الألوان
    final PdfColor goldColor = PdfColor.fromInt(0xFFDAA520);
    final PdfColor deepBlue = PdfColor.fromInt(0xFF1A237E);
    
    // البيانات
    String cleanCourseName = widget.courseName.replaceAll(RegExp(r'[()]'), '');
    String dateStr = DateFormat('yyyy/MM/dd').format(DateTime.now());

    pdf.addPage(
      pw.Page(
        pageFormat: PdfPageFormat.a4.landscape,
        theme: pw.ThemeData.withFont(base: ttf, bold: ttf), 
        textDirection: pw.TextDirection.rtl,
        margin: const pw.EdgeInsets.all(0),
        build: (pw.Context context) {
          return pw.Stack(
            alignment: pw.Alignment.center,
            children: [
              // 1. الخلفية والعلامة المائية
              pw.Container(
                width: double.infinity,
                height: double.infinity,
                color: PdfColors.white,
              ),
              pw.Center(
                child: pw.Opacity(
                  opacity: 0.03,
                  child: pw.Text("< />", style: pw.TextStyle(fontSize: 400, color: PdfColors.grey)),
                ),
              ),

              // 2. الإطار الزخرفي
              pw.Container(
                margin: const pw.EdgeInsets.all(20),
                decoration: pw.BoxDecoration(
                  border: pw.Border.all(color: goldColor, width: 5),
                  borderRadius: pw.BorderRadius.circular(10),
                ),
                child: pw.Container(
                  margin: const pw.EdgeInsets.all(5),
                  decoration: pw.BoxDecoration(
                    border: pw.Border.all(color: deepBlue, width: 1.5),
                    borderRadius: pw.BorderRadius.circular(5),
                  ),
                ),
              ),

              // 3. المحتوى
              pw.Padding(
                padding: const pw.EdgeInsets.symmetric(horizontal: 60, vertical: 40),
                child: pw.Column(
                  mainAxisAlignment: pw.MainAxisAlignment.spaceBetween,
                  children: [
                    // الرأس
                    pw.Column(
                      children: [
                        pw.Text("CERTIFICATE OF COMPLETION", 
                          style: pw.TextStyle(fontSize: 16, color: goldColor, letterSpacing: 2),
                          textDirection: pw.TextDirection.ltr
                        ),
                        pw.SizedBox(height: 5),
                        pw.Text("شهادة إتمام وتفوق", 
                          style: pw.TextStyle(fontSize: 38, color: deepBlue, fontWeight: pw.FontWeight.bold)
                        ),
                        pw.SizedBox(height: 10),
                        pw.Text("تمنح أكاديمية يُسر هذه الشهادة إلى:", style: pw.TextStyle(fontSize: 14, color: PdfColors.grey700)),
                      ],
                    ),

                    // اسم الطالب
                    pw.Column(
                      children: [
                        pw.Text(_studentName, style: pw.TextStyle(fontSize: 42, color: PdfColors.black)),
                        pw.SizedBox(height: 5),
                        pw.Container(width: 200, height: 1.5, color: goldColor),
                      ],
                    ),

                    // تفاصيل الكورس
                    pw.Column(
                      children: [
                        pw.Text("لإتمامه بنجاح المسار التدريبي الكامل في:", style: pw.TextStyle(fontSize: 14, color: PdfColors.grey700)),
                        pw.SizedBox(height: 8),
                        pw.Text(cleanCourseName, style: pw.TextStyle(fontSize: 24, color: deepBlue)),
                      ],
                    ),

                    // التذييل
                    pw.Row(
                      mainAxisAlignment: pw.MainAxisAlignment.spaceBetween,
                      crossAxisAlignment: pw.CrossAxisAlignment.end,
                      children: [
                        // QR
                        pw.Column(
                          crossAxisAlignment: pw.CrossAxisAlignment.center,
                          children: [
                            pw.BarcodeWidget(
                              barcode: pw.Barcode.qrCode(),
                              data: "https://yosr-academy.web.app/verify/$_certificateId",
                              width: 50,
                              height: 50,
                            ),
                            pw.SizedBox(height: 5),
                            pw.Text("ID: $_certificateId", style: pw.TextStyle(fontSize: 8, color: PdfColors.grey600)),
                          ],
                        ),

                        // التوقيعات
                        pw.Row(
                          children: [
                            _buildSignature("التاريخ", dateStr),
                            pw.SizedBox(width: 40),
                            _buildSignature("مدير المنصة", "Yosr Academy"),
                          ],
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              
              // 4. الشعار الذهبي (تم إصلاحه باستخدام CustomPaint لرسم علامة صح)
              pw.Positioned(
                top: 40,
                right: 40,
                child: pw.Container(
                  width: 35,
                  height: 35,
                  decoration: pw.BoxDecoration(shape: pw.BoxShape.circle, color: goldColor),
                  child: pw.Center(
                    child: pw.CustomPaint(
                      size: const PdfPoint(15, 15),
                      painter: (PdfGraphics canvas, PdfPoint size) {
                        // رسم علامة صح يدوياً (Vector)
                        canvas
                          ..setColor(PdfColors.white)
                          ..setLineWidth(2.5)
                          ..moveTo(3, 7)  // بداية الخط القصير
                          ..lineTo(6, 11) // الزاوية
                          ..lineTo(12, 3) // نهاية الخط الطويل
                          ..strokePath();
                      },
                    ),
                  ),
                )
              )
            ],
          );
        },
      ),
    );

    return pdf.save();
  }

  pw.Widget _buildSignature(String title, String value) {
    return pw.Column(
      crossAxisAlignment: pw.CrossAxisAlignment.center,
      children: [
        pw.Text(value, style: pw.TextStyle(fontSize: 12, fontWeight: pw.FontWeight.bold)),
        pw.SizedBox(height: 5),
        pw.Container(width: 80, height: 1, color: PdfColors.black),
        pw.SizedBox(height: 2),
        pw.Text(title, style: pw.TextStyle(fontSize: 10, color: PdfColors.grey600)),
      ],
    );
  }

  void _openPreviewScreen() {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (context) => Scaffold(
          appBar: AppBar(title: Text("معاينة الشهادة"), backgroundColor: Color(0xFF1A237E), foregroundColor: Colors.white),
          body: PdfPreview(
            build: (format) => _generatePdf(format),
            canChangeOrientation: false,
            canChangePageFormat: false,
            allowSharing: true,
            allowPrinting: true,
            initialPageFormat: PdfPageFormat.a4.landscape,
            pdfFileName: "Certificate_$_certificateId.pdf",
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.grey[50],
      appBar: AppBar(title: Text("إصدار الشهادة"), centerTitle: true),
      body: Center(
        child: _isLoadingData 
          ? CircularProgressIndicator()
          : Padding(
            padding: const EdgeInsets.all(20.0),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                // بطاقة المعاينة
                Container(
                  height: 200,
                  width: double.infinity,
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(20),
                    boxShadow: [BoxShadow(color: Colors.black12, blurRadius: 15, offset: Offset(0, 5))],
                    border: Border.all(color: Color(0xFFDAA520), width: 2)
                  ),
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.verified, size: 60, color: Color(0xFFDAA520)),
                      SizedBox(height: 10),
                      Text("شهادة إتمام المسار", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Color(0xFF1A237E))),
                      SizedBox(height: 5),
                      Text(_studentName, style: TextStyle(fontSize: 16)),
                      SizedBox(height: 5),
                      Text("ID: $_certificateId", style: TextStyle(fontSize: 12, color: Colors.grey)),
                    ],
                  ),
                ),
                SizedBox(height: 40),
                
                // زر التحميل
                SizedBox(
                  width: double.infinity,
                  height: 55,
                  child: ElevatedButton.icon(
                    onPressed: _openPreviewScreen,
                    icon: Icon(Icons.remove_red_eye_rounded),
                    label: Text("معاينة وتحميل الشهادة", style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Color(0xFF1A237E),
                      foregroundColor: Colors.white,
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(15)),
                      elevation: 5
                    ),
                  ),
                ),
                SizedBox(height: 15),
                Text("يمكنك طباعة الشهادة أو مشاركتها مباشرة بعد المعاينة", style: TextStyle(color: Colors.grey, fontSize: 12)),
              ],
            ),
          ),
      ),
    );
  }
}