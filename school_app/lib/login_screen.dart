import 'dart:io';
import 'package:flutter/gestures.dart'; 
import 'package:flutter/material.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_storage/firebase_storage.dart'; 
import 'package:image_picker/image_picker.dart';
import 'package:animate_do/animate_do.dart';
import 'package:url_launcher/url_launcher.dart'; 
import 'student_dashboard.dart';
import 'teacher_dashboard.dart';

class LoginScreen extends StatefulWidget {
  @override
  _LoginScreenState createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  
  // المتحكمات
  final _usernameController = TextEditingController();
  final _passwordController = TextEditingController();
  final _nameController = TextEditingController();
  
  // التركيز
  final _usernameFocus = FocusNode();
  final _passwordFocus = FocusNode();
  final _nameFocus = FocusNode();

  File? _userImageFile;
  bool isTeacher = false;
  bool isRegistering = false;
  bool isLoading = false;
  bool _isImageProcessing = false; 
  bool _obscurePassword = true;
  bool _acceptedTerms = false;

  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    _nameController.dispose();
    _usernameFocus.dispose();
    _passwordFocus.dispose();
    _nameFocus.dispose();
    super.dispose();
  }

  Future<void> _pickImage() async {
    setState(() => _isImageProcessing = true);
    try {
      final pickedImage = await ImagePicker().pickImage(source: ImageSource.gallery, imageQuality: 50);
      if (pickedImage != null) {
        setState(() => _userImageFile = File(pickedImage.path));
      }
    } finally {
      setState(() => _isImageProcessing = false);
    }
  }

  void _launchTerms() async {
    const url = 'https://your-app-terms.com'; 
    if (await canLaunchUrl(Uri.parse(url))) {
      await launchUrl(Uri.parse(url));
    } else {
      _showSnack("تعذر فتح الرابط", Colors.red);
    }
  }

  Future<void> _submit() async {
    FocusScope.of(context).unfocus();

    if (!_formKey.currentState!.validate()) return;

    if (isRegistering) {
      if (_userImageFile == null) {
        _showSnack('يرجى اختيار صورة شخصية لملفك', Colors.orange);
        return;
      }
      if (!_acceptedTerms) {
        _showSnack('يجب الموافقة على الشروط والأحكام', Colors.redAccent);
        return;
      }
    }

    setState(() => isLoading = true);

    try {
      final username = _usernameController.text.trim();
      final password = _passwordController.text.trim();
      // إنشاء إيميل وهمي لأن تسجيل الدخول يتطلب إيميل
      final fakeEmail = "$username@yosr.app"; 

      if (isRegistering) {
        UserCredential cred = await FirebaseAuth.instance.createUserWithEmailAndPassword(email: fakeEmail, password: password);
        
        String? imageUrl;
        if (_userImageFile != null) {
          final ref = FirebaseStorage.instance.ref().child('user_images').child('${cred.user!.uid}.jpg');
          await ref.putFile(_userImageFile!);
          imageUrl = await ref.getDownloadURL();
        }

        await FirebaseFirestore.instance.collection('users').doc(cred.user!.uid).set({
          'username': username,
          'name': _nameController.text.trim(),
          'role': isTeacher ? 'teacher' : 'student',
          'photoUrl': imageUrl,
          'createdAt': FieldValue.serverTimestamp(),
          'totalPoints': 0,
        });
      } else {
        await FirebaseAuth.instance.signInWithEmailAndPassword(email: fakeEmail, password: password);
      }
      
      if (FirebaseAuth.instance.currentUser != null) {
        _navigateBasedOnRole();
      }
    } catch (e) {
      print("DEBUG ERROR: $e"); // سيظهر الخطأ الحقيقي في الـ Console
      
      String msg = "حدث خطأ غير متوقع";
      String errorStr = e.toString().toLowerCase();

      if (errorStr.contains('email-already-in-use')) msg = "اسم المستخدم هذا محجوز مسبقاً";
      else if (errorStr.contains('user-not-found') || errorStr.contains('wrong-password') || errorStr.contains('invalid-credential')) msg = "خطأ في اسم المستخدم أو كلمة المرور";
      else if (errorStr.contains('invalid-email')) msg = "اسم المستخدم يحتوي على رموز غير مقبولة";
      else if (errorStr.contains('network-request-failed')) msg = "تحقق من اتصال الإنترنت";
      else if (errorStr.contains('too-many-requests')) msg = "محاولات كثيرة خاطئة، حاول لاحقاً";

      _showSnack(msg, Colors.red);
    } finally {
      if (mounted) setState(() => isLoading = false);
    }
  }

  Future<void> _googleSignIn() async {
    _showSnack("يتطلب تفعيل خدمة Google Sign-In في لوحة التحكم", Colors.orange);
  }

  Future<void> _navigateBasedOnRole() async {
    try {
      var userDoc = await FirebaseFirestore.instance.collection('users').doc(FirebaseAuth.instance.currentUser!.uid).get();
      if (userDoc.exists) {
        var role = userDoc.data()?['role'] ?? 'student';
        if (mounted) {
          Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => role == 'teacher' ? TeacherDashboard() : StudentDashboard()));
        }
      } else {
        // حالة نادرة: المستخدم موجود في Auth ولكن ليس في Firestore
        _showSnack("بيانات المستخدم غير مكتملة", Colors.orange);
      }
    } catch (e) {
      _showSnack("فشل تحميل البيانات", Colors.red);
    }
  }

  void _showSnack(String msg, Color color) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg), backgroundColor: color, behavior: SnackBarBehavior.floating));
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final cardColor = isDark ? Color(0xFF1E1E2C) : Colors.white;
    // اللون البنفسجي الأساسي للنصوص (بدلاً من الأسود)
    final primaryTextColor = Color(0xFF6C63FF); 
    final fieldTextColor = isDark ? Colors.white : Colors.black87;

    return Scaffold(
      body: Container(
        height: double.infinity,
        decoration: BoxDecoration(
          gradient: LinearGradient(colors: [Color(0xFF6C63FF), Color(0xFF4834D4)], begin: Alignment.topLeft, end: Alignment.bottomRight)
        ),
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24.0),
            child: Column(
              children: [
                ZoomIn(
                  child: Container(
                    padding: const EdgeInsets.all(20),
                    decoration: BoxDecoration(color: Colors.white, shape: BoxShape.circle, boxShadow: [BoxShadow(color: Colors.black26, blurRadius: 15)]),
                    child: const Icon(Icons.code_rounded, size: 60, color: Color(0xFF6C63FF)),
                  ),
                ),
                const SizedBox(height: 20),
                FadeInDown(child: const Text("يُــــسر", style: TextStyle(fontSize: 36, fontWeight: FontWeight.bold, color: Colors.white, letterSpacing: 1.5))),
                const SizedBox(height: 40),
                
                FadeInUp(
                  child: Container(
                    padding: const EdgeInsets.all(30),
                    decoration: BoxDecoration(
                      color: cardColor.withOpacity(0.95),
                      borderRadius: BorderRadius.circular(30),
                      boxShadow: [BoxShadow(color: Colors.black26, blurRadius: 20, offset: Offset(0, 10))]
                    ),
                    child: Form(
                      key: _formKey,
                      child: AnimatedSwitcher(
                        duration: Duration(milliseconds: 500),
                        transitionBuilder: (child, animation) => FadeTransition(opacity: animation, child: SizeTransition(sizeFactor: animation, child: child)),
                        child: isRegistering 
                          ? _buildRegisterForm(primaryTextColor, fieldTextColor) 
                          : _buildLoginForm(primaryTextColor, fieldTextColor),
                      ),
                    ),
                  ),
                ),
                
                const SizedBox(height: 30),
                _buildFooterCredits(),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildLoginForm(Color headerColor, Color inputColor) {
    return Column(
      key: ValueKey("login"),
      children: [
        // تم التعديل: لون بنفسجي وبدون إيموجي
        Text("مرحباً بعودتك", style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold, color: headerColor)),
        SizedBox(height: 25),
        _buildTextField(
          controller: _usernameController,
          focusNode: _usernameFocus,
          nextFocus: _passwordFocus,
          label: "اسم المستخدم",
          icon: Icons.person,
          textColor: inputColor,
        ),
        SizedBox(height: 15),
        _buildTextField(
          controller: _passwordController,
          focusNode: _passwordFocus,
          label: "كلمة المرور",
          icon: Icons.lock,
          isPassword: true,
          textColor: inputColor,
          onSubmit: (_) => _submit(),
        ),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton(
            onPressed: () => _showSnack("راجع مسؤول النظام لاستعادة كلمة المرور", Colors.blue),
            child: Text("نسيت كلمة المرور؟", style: TextStyle(color: Color(0xFF6C63FF))),
          ),
        ),
        SizedBox(height: 20),
        _buildSubmitButton("تسجيل الدخول"),
        SizedBox(height: 20),
        _buildSocialLoginSection(),
        SizedBox(height: 20),
        _buildToggleRow("ليس لديك حساب؟", "أنشئ حساباً", true),
      ],
    );
  }

  Widget _buildRegisterForm(Color headerColor, Color inputColor) {
    return Column(
      key: ValueKey("register"),
      children: [
        // تم التعديل: لون بنفسجي وبدون إيموجي
        Text("حساب جديد", style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold, color: headerColor)),
        SizedBox(height: 20),
        GestureDetector(
          onTap: _pickImage,
          child: Semantics(
            label: "اختيار صورة شخصية",
            button: true,
            child: Stack(
              children: [
                CircleAvatar(
                  radius: 45,
                  backgroundColor: Colors.grey[200],
                  backgroundImage: _userImageFile != null ? FileImage(_userImageFile!) : null,
                  child: _userImageFile == null ? Icon(Icons.add_a_photo, size: 30, color: Colors.grey) : null,
                ),
                if (_isImageProcessing)
                  Positioned.fill(child: Container(decoration: BoxDecoration(shape: BoxShape.circle, color: Colors.black26), child: Center(child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2)))),
                
                if (!_isImageProcessing && _userImageFile == null)
                  Positioned(bottom: 0, right: 0, child: CircleAvatar(backgroundColor: Color(0xFF6C63FF), radius: 15, child: Icon(Icons.add, color: Colors.white, size: 15)))
              ],
            ),
          ),
        ),
        SizedBox(height: 20),
        _buildTextField(
          controller: _nameController,
          focusNode: _nameFocus,
          nextFocus: _usernameFocus,
          label: "الاسم الكامل",
          icon: Icons.badge,
          textColor: inputColor,
        ),
        SizedBox(height: 15),
        _buildTextField(
          controller: _usernameController,
          focusNode: _usernameFocus,
          nextFocus: _passwordFocus,
          label: "اسم المستخدم (English)",
          icon: Icons.person,
          textColor: inputColor,
          // منع المسافات لأنها تسبب خطأ في الإيميل الوهمي
          validator: (val) => val!.contains(" ") ? "يجب ألا يحتوي على مسافات" : null,
        ),
        SizedBox(height: 15),
        _buildTextField(
          controller: _passwordController,
          focusNode: _passwordFocus,
          label: "كلمة المرور",
          icon: Icons.lock,
          isPassword: true,
          textColor: inputColor,
          onChanged: (val) => setState(() {}),
        ),
        if (_passwordController.text.isNotEmpty) ...[
          _buildPasswordStrengthBar(),
          Padding(
            padding: const EdgeInsets.only(top: 5, right: 5),
            child: Align(
              alignment: Alignment.centerRight,
              child: Text("يفضل: حرف كبير، رقم، ورمز خاص", style: TextStyle(fontSize: 10, color: Colors.grey)),
            ),
          )
        ],
        SizedBox(height: 15),
        Row(children: [
           Expanded(child: _roleBtn("طالب", !isTeacher, () => setState(() => isTeacher = false))),
           SizedBox(width: 10),
           Expanded(child: _roleBtn("معلم", isTeacher, () => setState(() => isTeacher = true))),
        ]),
        SizedBox(height: 10),
        CheckboxListTile(
          value: _acceptedTerms,
          activeColor: Color(0xFF6C63FF),
          contentPadding: EdgeInsets.zero,
          title: RichText(
            text: TextSpan(
              style: TextStyle(fontSize: 12, color: inputColor, fontFamily: 'Cairo'), 
              children: [
                TextSpan(text: "أوافق على "),
                TextSpan(
                  text: "الشروط والأحكام",
                  style: TextStyle(color: Color(0xFF6C63FF), fontWeight: FontWeight.bold, decoration: TextDecoration.underline),
                  recognizer: TapGestureRecognizer()..onTap = _launchTerms,
                ),
              ],
            ),
          ),
          onChanged: (val) => setState(() => _acceptedTerms = val!),
        ),
        SizedBox(height: 10),
        _buildSubmitButton("إنشاء حساب"),
        SizedBox(height: 15),
        _buildToggleRow("لديك حساب بالفعل؟", "تسجيل دخول", false),
      ],
    );
  }

  Widget _buildTextField({
    required TextEditingController controller,
    required String label,
    required IconData icon,
    required Color textColor,
    FocusNode? focusNode,
    FocusNode? nextFocus,
    bool isPassword = false,
    Function(String)? onSubmit,
    Function(String)? onChanged,
    String? Function(String?)? validator,
  }) {
    return TextFormField(
      controller: controller,
      focusNode: focusNode,
      obscureText: isPassword && _obscurePassword,
      style: TextStyle(color: textColor),
      textInputAction: nextFocus != null ? TextInputAction.next : TextInputAction.done,
      onFieldSubmitted: (_) => nextFocus != null ? FocusScope.of(context).requestFocus(nextFocus) : (onSubmit != null ? onSubmit(_) : null),
      onChanged: onChanged,
      validator: validator ?? (val) {
        if (val == null || val.isEmpty) return "هذا الحقل مطلوب";
        if (val.length < 3) return "قصير جداً";
        return null;
      },
      decoration: InputDecoration(
        labelText: label,
        labelStyle: TextStyle(color: Colors.grey),
        prefixIcon: Icon(icon, color: Color(0xFF6C63FF)),
        suffixIcon: isPassword 
          ? IconButton(icon: Icon(_obscurePassword ? Icons.visibility_outlined : Icons.visibility_off_outlined, color: Colors.grey), onPressed: () => setState(() => _obscurePassword = !_obscurePassword)) 
          : null,
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(15)),
        enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(15), borderSide: BorderSide(color: Colors.grey.withOpacity(0.3))),
      ),
    );
  }

  Widget _buildPasswordStrengthBar() {
    String pass = _passwordController.text;
    double strength = 0;
    if (pass.length >= 6) strength += 0.2;
    if (pass.length >= 8) strength += 0.2;
    if (pass.contains(RegExp(r'[A-Z]'))) strength += 0.2;
    if (pass.contains(RegExp(r'[0-9]'))) strength += 0.2;
    if (pass.contains(RegExp(r'[!@#\$&*~]'))) strength += 0.2;

    Color color = strength < 0.4 ? Colors.red : (strength < 0.8 ? Colors.orange : Colors.green);

    return Padding(
      padding: const EdgeInsets.only(top: 8.0, left: 5, right: 5),
      child: LinearProgressIndicator(value: strength, color: color, backgroundColor: Colors.grey[200], minHeight: 4),
    );
  }

  Widget _buildSubmitButton(String text) {
    return Semantics(
      button: true,
      label: text,
      child: SizedBox(
        width: double.infinity,
        height: 50,
        child: ElevatedButton(
          onPressed: isLoading ? null : _submit,
          style: ElevatedButton.styleFrom(
            backgroundColor: Color(0xFF6C63FF),
            foregroundColor: Colors.white,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(15)),
            elevation: 5,
          ),
          child: isLoading 
            ? SizedBox(height: 20, width: 20, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2)) 
            : Text(text, style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
        ),
      ),
    );
  }

  Widget _buildSocialLoginSection() {
    return Column(
      children: [
        Row(children: [Expanded(child: Divider()), Padding(padding: EdgeInsets.symmetric(horizontal: 10), child: Text("أو تابع باستخدام", style: TextStyle(color: Colors.grey, fontSize: 12))), Expanded(child: Divider())]),
        SizedBox(height: 15),
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            _socialBtn(Icons.apple, Colors.black, () => _showSnack("قريباً على Apple", Colors.black)),
            SizedBox(width: 20),
            _socialBtn(Icons.g_mobiledata, Colors.red, _googleSignIn),
          ],
        )
      ],
    );
  }

  Widget _socialBtn(IconData icon, Color color, VoidCallback onTap) {
    return InkWell(
      onTap: onTap,
      child: Container(
        padding: EdgeInsets.all(10),
        decoration: BoxDecoration(border: Border.all(color: Colors.grey.withOpacity(0.3)), shape: BoxShape.circle),
        child: Icon(icon, color: color, size: 28),
      ),
    );
  }

  Widget _buildToggleRow(String text, String actionText, bool toRegister) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Text(text, style: TextStyle(color: Colors.grey)),
        TextButton(
          onPressed: () => setState(() { isRegistering = toRegister; _formKey.currentState?.reset(); _userImageFile = null; _isImageProcessing = false; }),
          child: Text(actionText, style: TextStyle(fontWeight: FontWeight.bold, color: Color(0xFF6C63FF))),
        )
      ],
    );
  }

  Widget _roleBtn(String txt, bool sel, VoidCallback tap) {
    return Semantics(
      button: true,
      selected: sel,
      label: "دور $txt",
      child: InkWell(
        onTap: tap,
        borderRadius: BorderRadius.circular(10),
        child: AnimatedContainer(
          duration: Duration(milliseconds: 300),
          padding: EdgeInsets.symmetric(vertical: 12),
          decoration: BoxDecoration(
            color: sel ? Color(0xFF6C63FF) : Colors.grey[100], 
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: sel ? Color(0xFF6C63FF) : Colors.transparent)
          ),
          child: Center(child: Text(txt, style: TextStyle(color: sel ? Colors.white : Colors.black54, fontWeight: FontWeight.bold))),
        ),
      ),
    );
  }

  Widget _buildFooterCredits() {
    return Column(
      children: [
        const Text("فريق العمل", style: TextStyle(color: Colors.white70, fontSize: 12, fontWeight: FontWeight.bold)),
        const SizedBox(height: 8),
        const Text(
          "شروق عمر   •   اسماء رضا   •   الاء وائل\nروان محمد   •   اسماء السيد   •   اسماء رشاد",
          textAlign: TextAlign.center,
          style: TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.w500, height: 1.6),
        ),
      ],
    );
  }
}