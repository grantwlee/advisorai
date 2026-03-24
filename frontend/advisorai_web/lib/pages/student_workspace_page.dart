import 'package:flutter/material.dart';

import '../services/api_service.dart';

class StudentWorkspacePage extends StatefulWidget {
  final String studentId;
  final String pageTitle;
  final bool showBackButton;

  const StudentWorkspacePage({
    super.key,
    required this.studentId,
    required this.pageTitle,
    required this.showBackButton,
  });

  @override
  State<StudentWorkspacePage> createState() => _StudentWorkspacePageState();
}

class _StudentWorkspacePageState extends State<StudentWorkspacePage> {
  final ApiService _api = ApiService();
  final TextEditingController _questionController = TextEditingController();

  bool _isLoadingProfile = true;
  bool _isSubmittingQuestion = false;
  bool _isUpdatingCourses = false;
  String? _profileError;
  Map<String, dynamic>? _student;
  final List<_AdvisorExchange> _history = [];

  @override
  void initState() {
    super.initState();
    _loadStudent();
  }

  @override
  void dispose() {
    _questionController.dispose();
    super.dispose();
  }

  Future<void> _loadStudent() async {
    setState(() {
      _isLoadingProfile = true;
      _profileError = null;
    });

    try {
      final data = await _api.getStudentDetail(widget.studentId);
      if (!mounted) return;
      setState(() {
        _student = data;
        _isLoadingProfile = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _profileError = e.toString();
        _isLoadingProfile = false;
      });
    }
  }

  Future<void> _submitQuestion() async {
    final question = _questionController.text.trim();
    if (question.isEmpty || _student == null) return;

    FocusScope.of(context).unfocus();
    setState(() {
      _isSubmittingQuestion = true;
      _history.insert(0, _AdvisorExchange(question: question));
    });
    _questionController.clear();

    try {
      final response = await _api.queryAdvisor(
        question: question,
        studentId: widget.studentId,
      );
      if (!mounted) return;
      setState(() {
        _history[0] = _history[0].copyWith(response: response);
        _isSubmittingQuestion = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _history[0] = _history[0].copyWith(
          response: {
            'status': 'refused',
            'answer': '',
            'refusal_reason': e.toString(),
            'citations': [],
            'retrieved_chunks': [],
            'verifier': {
              'passed': false,
              'issues': [e.toString()],
            },
          },
        );
        _isSubmittingQuestion = false;
      });
    }
  }

  Future<void> _openAddCourseDialog() async {
    final result = await showDialog<_AddCourseFormData>(
      context: context,
      builder: (context) => const _AddCourseDialog(),
    );
    if (result == null) return;

    setState(() {
      _isUpdatingCourses = true;
    });
    try {
      await _api.addStudentCourse(
        studentId: widget.studentId,
        courseCode: result.courseCode,
        title: result.title,
        status: result.status,
        credits: result.credits,
        term: result.term,
        grade: result.grade,
      );
      await _loadStudent();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Unable to save course: $e')),
      );
    } finally {
      if (mounted) {
        setState(() {
          _isUpdatingCourses = false;
        });
      }
    }
  }

  Future<void> _deleteCourse(int recordId) async {
    setState(() {
      _isUpdatingCourses = true;
    });
    try {
      await _api.deleteStudentCourse(widget.studentId, recordId);
      await _loadStudent();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Unable to remove course: $e')),
      );
    } finally {
      if (mounted) {
        setState(() {
          _isUpdatingCourses = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        automaticallyImplyLeading: widget.showBackButton,
        title: Text(widget.pageTitle),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            tooltip: 'Refresh',
            onPressed: _loadStudent,
          ),
          if (!widget.showBackButton)
            IconButton(
              icon: const Icon(Icons.search),
              tooltip: 'Student Search',
              onPressed: () {
                Navigator.pushNamed(context, '/student-search');
              },
            ),
          if (!widget.showBackButton)
            IconButton(
              icon: const Icon(Icons.logout),
              tooltip: 'Logout',
              onPressed: () {
                Navigator.pushReplacementNamed(context, '/');
              },
            ),
        ],
      ),
      body: _isLoadingProfile
          ? const Center(child: CircularProgressIndicator())
          : _profileError != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text(
                      _profileError!,
                      style: const TextStyle(color: Colors.red),
                      textAlign: TextAlign.center,
                    ),
                  ),
                )
              : _student == null
                  ? const Center(child: Text('Student not found'))
                  : RefreshIndicator(
                      onRefresh: _loadStudent,
                      child: ListView(
                        padding: const EdgeInsets.all(16),
                        children: [
                          _StudentSummaryCard(student: _student!),
                          const SizedBox(height: 20),
                          _TrackedCoursesCard(
                            courses:
                                (_student!['courses'] as List<dynamic>? ?? [])
                                    .cast<Map<String, dynamic>>(),
                            isBusy: _isUpdatingCourses,
                            onAddCourse: _openAddCourseDialog,
                            onDeleteCourse: _deleteCourse,
                          ),
                          const SizedBox(height: 20),
                          _AdvisorQueryCard(
                            controller: _questionController,
                            isSubmitting: _isSubmittingQuestion,
                            onSubmit: _submitQuestion,
                          ),
                          const SizedBox(height: 20),
                          if (_history.isEmpty)
                            const _EmptyStateCard()
                          else
                            ..._history.map((exchange) => Padding(
                                  padding: const EdgeInsets.only(bottom: 16),
                                  child: _AdvisorExchangeCard(exchange: exchange),
                                )),
                        ],
                      ),
                    ),
    );
  }
}

class _StudentSummaryCard extends StatelessWidget {
  final Map<String, dynamic> student;

  const _StudentSummaryCard({required this.student});

  @override
  Widget build(BuildContext context) {
    final name = student['name']?.toString() ?? '';
    final initials = name.isEmpty
        ? 'S'
        : name
            .split(' ')
            .where((part) => part.isNotEmpty)
            .take(2)
            .map((part) => part[0].toUpperCase())
            .join();

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            CircleAvatar(
              radius: 32,
              backgroundColor: Theme.of(context).colorScheme.primaryContainer,
              child: Text(
                initials,
                style: TextStyle(
                  fontSize: 24,
                  fontWeight: FontWeight.bold,
                  color: Theme.of(context).colorScheme.onPrimaryContainer,
                ),
              ),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Wrap(
                runSpacing: 10,
                spacing: 12,
                children: [
                  SizedBox(
                    width: double.infinity,
                    child: Text(
                      name,
                      style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                            fontWeight: FontWeight.bold,
                          ),
                    ),
                  ),
                  _InfoChip(
                    icon: Icons.badge_outlined,
                    label: student['student_id']?.toString() ?? '',
                  ),
                  _InfoChip(
                    icon: Icons.school_outlined,
                    label: student['program']?.toString() ?? '',
                  ),
                  _InfoChip(
                    icon: Icons.calendar_month_outlined,
                    label: student['bulletin_year']?.toString() ?? '',
                  ),
                  _InfoChip(
                    icon: Icons.mail_outline,
                    label: student['email']?.toString() ?? '',
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _InfoChip extends StatelessWidget {
  final IconData icon;
  final String label;

  const _InfoChip({required this.icon, required this.label});

  @override
  Widget build(BuildContext context) {
    return Chip(
      avatar: Icon(icon, size: 16),
      label: Text(label),
    );
  }
}

class _TrackedCoursesCard extends StatelessWidget {
  final List<Map<String, dynamic>> courses;
  final bool isBusy;
  final VoidCallback onAddCourse;
  final ValueChanged<int> onDeleteCourse;

  const _TrackedCoursesCard({
    required this.courses,
    required this.isBusy,
    required this.onAddCourse,
    required this.onDeleteCourse,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    'Tracked Courses',
                    style: Theme.of(context).textTheme.titleLarge?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                  ),
                ),
                FilledButton.icon(
                  onPressed: isBusy ? null : onAddCourse,
                  icon: const Icon(Icons.add),
                  label: const Text('Add Course'),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              'These records power the scoped advising logic for “What do I have left?”',
              style: TextStyle(color: Colors.grey[700]),
            ),
            const SizedBox(height: 16),
            if (isBusy) const LinearProgressIndicator(),
            if (courses.isEmpty)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 12),
                child: Text('No courses tracked yet.'),
              )
            else
              ...courses.map(
                (courseRecord) => _TrackedCourseTile(
                  courseRecord: courseRecord,
                  onDelete: () => onDeleteCourse(courseRecord['id'] as int),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _TrackedCourseTile extends StatelessWidget {
  final Map<String, dynamic> courseRecord;
  final VoidCallback onDelete;

  const _TrackedCourseTile({
    required this.courseRecord,
    required this.onDelete,
  });

  Color _statusColor(BuildContext context, String status) {
    switch (status) {
      case 'completed':
      case 'transfer':
      case 'waived':
        return Colors.green.shade700;
      case 'in_progress':
        return Theme.of(context).colorScheme.primary;
      default:
        return Colors.orange.shade700;
    }
  }

  @override
  Widget build(BuildContext context) {
    final course = (courseRecord['course'] as Map<String, dynamic>? ?? {});
    final status = courseRecord['status']?.toString() ?? 'planned';

    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor:
              _statusColor(context, status).withValues(alpha: 0.12),
          child: Icon(
            status == 'completed' ? Icons.check : Icons.menu_book_outlined,
            color: _statusColor(context, status),
          ),
        ),
        title: Text(
          '${course['code'] ?? ''} • ${course['title'] ?? ''}',
          style: const TextStyle(fontWeight: FontWeight.w600),
        ),
        subtitle: Text(
          [
            status.replaceAll('_', ' '),
            if (courseRecord['term'] != null) courseRecord['term'].toString(),
            if (courseRecord['grade'] != null) 'Grade ${courseRecord['grade']}',
          ].join(' • '),
        ),
        trailing: IconButton(
          icon: const Icon(Icons.delete_outline),
          tooltip: 'Remove course',
          onPressed: onDelete,
        ),
      ),
    );
  }
}

class _AdvisorQueryCard extends StatelessWidget {
  final TextEditingController controller;
  final bool isSubmitting;
  final VoidCallback onSubmit;

  const _AdvisorQueryCard({
    required this.controller,
    required this.isSubmitting,
    required this.onSubmit,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'AdvisorAI',
              style: Theme.of(context).textTheme.titleLarge?.copyWith(
                    fontWeight: FontWeight.bold,
                  ),
            ),
            const SizedBox(height: 8),
            Text(
              'Ask about bulletin requirements, compare policies, or try “What do I have left?”',
              style: TextStyle(color: Colors.grey[700]),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: controller,
              minLines: 2,
              maxLines: 4,
              onSubmitted: (_) => onSubmit(),
              decoration: const InputDecoration(
                hintText: 'Example: What do I have left?',
                prefixIcon: Icon(Icons.smart_toy_outlined),
              ),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      _SuggestionChip(
                        label: 'What do I have left?',
                        onTap: () => controller.text = 'What do I have left?',
                      ),
                      _SuggestionChip(
                        label: 'Which bulletin year applies to me?',
                        onTap: () =>
                            controller.text = 'Which bulletin year applies to me?',
                      ),
                      _SuggestionChip(
                        label: 'What does INFS 428 cover?',
                        onTap: () => controller.text = 'What does INFS 428 cover?',
                      ),
                      _SuggestionChip(
                        label: 'What should I take next semester?',
                        onTap: () => controller.text =
                            'What should I take next semester?',
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 12),
                FilledButton.icon(
                  onPressed: isSubmitting ? null : onSubmit,
                  icon: isSubmitting
                      ? const SizedBox(
                          height: 16,
                          width: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.send),
                  label: const Text('Ask'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _SuggestionChip extends StatelessWidget {
  final String label;
  final VoidCallback onTap;

  const _SuggestionChip({required this.label, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return ActionChip(label: Text(label), onPressed: onTap);
  }
}

class _AdvisorExchangeCard extends StatelessWidget {
  final _AdvisorExchange exchange;

  const _AdvisorExchangeCard({required this.exchange});

  @override
  Widget build(BuildContext context) {
    final response = exchange.response;
    final status = response?['status']?.toString();
    final citations =
        (response?['citations'] as List<dynamic>? ?? []).cast<Map<String, dynamic>>();
    final retrieved = (response?['retrieved_chunks'] as List<dynamic>? ?? [])
        .cast<Map<String, dynamic>>();
    final verifier =
        (response?['verifier'] as Map<String, dynamic>? ?? const <String, dynamic>{});
    final auditSummary =
        response?['audit_summary'] as Map<String, dynamic>?;
    final planningContext =
        response?['planning_context'] as Map<String, dynamic>?;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              exchange.question,
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.bold,
                  ),
            ),
            const SizedBox(height: 12),
            if (response == null)
              const LinearProgressIndicator()
            else if (status == 'answered') ...[
              SelectableText(response['answer']?.toString() ?? ''),
              const SizedBox(height: 16),
              if (planningContext != null)
                _PlanningContextCard(planningContext: planningContext),
              if (auditSummary != null)
                _AuditSummaryCard(auditSummary: auditSummary),
              const _SectionTitle(title: 'Citations'),
              ...citations.map((citation) => _CitationCard(citation: citation)),
              const SizedBox(height: 8),
              const _SectionTitle(title: 'Retrieved Chunks'),
              ...retrieved.map((chunk) => _RetrievedChunkTile(chunk: chunk)),
              if (verifier['passed'] == false &&
                  (verifier['issues'] as List<dynamic>? ?? []).isNotEmpty) ...[
                const SizedBox(height: 8),
                const _SectionTitle(title: 'Verifier Notes'),
                ...((verifier['issues'] as List<dynamic>).map(
                  (issue) => Padding(
                    padding: const EdgeInsets.only(bottom: 4),
                    child: Text(issue.toString()),
                  ),
                )),
              ],
            ] else ...[
              Text(
                response['refusal_reason']?.toString() ?? 'The assistant refused to answer.',
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
              const SizedBox(height: 12),
              if ((verifier['issues'] as List<dynamic>? ?? []).isNotEmpty) ...[
                const _SectionTitle(title: 'Verifier Notes'),
                ...((verifier['issues'] as List<dynamic>).map(
                  (issue) => Padding(
                    padding: const EdgeInsets.only(bottom: 4),
                    child: Text(issue.toString()),
                  ),
                )),
              ],
            ],
          ],
        ),
      ),
    );
  }
}

class _AuditSummaryCard extends StatelessWidget {
  final Map<String, dynamic> auditSummary;

  const _AuditSummaryCard({required this.auditSummary});

  @override
  Widget build(BuildContext context) {
    final remaining =
        (auditSummary['remaining'] as List<dynamic>? ?? []).cast<Map<String, dynamic>>();
    final inProgress = (auditSummary['in_progress'] as List<dynamic>? ?? [])
        .cast<Map<String, dynamic>>();

    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Degree Audit Snapshot',
            style: Theme.of(context).textTheme.titleSmall?.copyWith(
                  fontWeight: FontWeight.bold,
                ),
          ),
          const SizedBox(height: 8),
          Text(auditSummary['scope_note']?.toString() ?? ''),
          const SizedBox(height: 8),
          Text(
            'Remaining: ${remaining.length} • In progress: ${inProgress.length} • Tracked requirements: ${auditSummary['total_required']}',
          ),
        ],
      ),
    );
  }
}

class _PlanningContextCard extends StatelessWidget {
  final Map<String, dynamic> planningContext;

  const _PlanningContextCard({required this.planningContext});

  @override
  Widget build(BuildContext context) {
    final recommended = (planningContext['recommended_next_courses']
                as List<dynamic>? ??
            [])
        .cast<Map<String, dynamic>>();
    final blocked =
        (planningContext['blocked_courses'] as List<dynamic>? ?? [])
            .cast<Map<String, dynamic>>();
    final gaps =
        (planningContext['context_gaps'] as List<dynamic>? ?? []).cast<dynamic>();

    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.secondaryContainer.withValues(
              alpha: 0.45,
            ),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Planning Snapshot',
            style: Theme.of(context).textTheme.titleSmall?.copyWith(
                  fontWeight: FontWeight.bold,
                ),
          ),
          const SizedBox(height: 8),
          Text(planningContext['scope_note']?.toString() ?? ''),
          const SizedBox(height: 8),
          Text(
            'Completed credits: ${planningContext['completed_credits'] ?? 0} • In progress: ${planningContext['in_progress_credits'] ?? 0} • Remaining credits: ${planningContext['remaining_credits'] ?? 0}',
          ),
          if (recommended.isNotEmpty) ...[
            const SizedBox(height: 12),
            const Text(
              'Recommended Next Courses',
              style: TextStyle(fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 6),
            ...recommended.map(
              (course) => Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text(
                  '${course['code']} • ${course['title']} (${course['credits']} cr)',
                ),
              ),
            ),
          ],
          if (blocked.isNotEmpty) ...[
            const SizedBox(height: 12),
            Text(
              'Blocked courses: ${blocked.length}',
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
          ],
          if (gaps.isNotEmpty) ...[
            const SizedBox(height: 12),
            ...gaps.map(
              (gap) => Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text(gap.toString()),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  final String title;

  const _SectionTitle({required this.title});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Text(
        title,
        style: Theme.of(context).textTheme.titleSmall?.copyWith(
              fontWeight: FontWeight.bold,
            ),
      ),
    );
  }
}

class _CitationCard extends StatelessWidget {
  final Map<String, dynamic> citation;

  const _CitationCard({required this.citation});

  @override
  Widget build(BuildContext context) {
    final pages = (citation['pageOccurrence'] as List<dynamic>? ?? []).join(', ');
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      color:
          Theme.of(context).colorScheme.primaryContainer.withValues(alpha: 0.4),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '${citation['chunkId']} • Bulletin ${citation['bulletin']}',
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
            if (pages.isNotEmpty) Text('Pages: $pages'),
            const SizedBox(height: 6),
            Text(citation['preview']?.toString() ?? ''),
          ],
        ),
      ),
    );
  }
}

class _RetrievedChunkTile extends StatelessWidget {
  final Map<String, dynamic> chunk;

  const _RetrievedChunkTile({required this.chunk});

  @override
  Widget build(BuildContext context) {
    final pages = (chunk['pageOccurrence'] as List<dynamic>? ?? []).join(', ');
    return ExpansionTile(
      tilePadding: EdgeInsets.zero,
      title: Text('${chunk['chunkId']} • score ${chunk['score'] ?? ''}'),
      subtitle: Text('Bulletin ${chunk['bulletin']}'),
      childrenPadding: const EdgeInsets.only(bottom: 12),
      children: [
        if (pages.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Text('Pages: $pages'),
          ),
        SelectableText(chunk['preview']?.toString() ?? ''),
      ],
    );
  }
}

class _EmptyStateCard extends StatelessWidget {
  const _EmptyStateCard();

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          children: [
            Icon(
              Icons.forum_outlined,
              size: 40,
              color: Theme.of(context).colorScheme.primary,
            ),
            const SizedBox(height: 12),
            Text(
              'No advising queries yet',
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.bold,
                  ),
            ),
            const SizedBox(height: 8),
            Text(
              'Ask a bulletin question or run a scoped degree audit for this student.',
              textAlign: TextAlign.center,
              style: TextStyle(color: Colors.grey[700]),
            ),
          ],
        ),
      ),
    );
  }
}

class _AdvisorExchange {
  final String question;
  final Map<String, dynamic>? response;

  const _AdvisorExchange({
    required this.question,
    this.response,
  });

  _AdvisorExchange copyWith({
    String? question,
    Map<String, dynamic>? response,
  }) {
    return _AdvisorExchange(
      question: question ?? this.question,
      response: response ?? this.response,
    );
  }
}

class _AddCourseDialog extends StatefulWidget {
  const _AddCourseDialog();

  @override
  State<_AddCourseDialog> createState() => _AddCourseDialogState();
}

class _AddCourseDialogState extends State<_AddCourseDialog> {
  final _formKey = GlobalKey<FormState>();
  final _courseCodeController = TextEditingController();
  final _titleController = TextEditingController();
  final _termController = TextEditingController();
  final _gradeController = TextEditingController();
  final _creditsController = TextEditingController(text: '3');

  String _status = 'completed';

  @override
  void dispose() {
    _courseCodeController.dispose();
    _titleController.dispose();
    _termController.dispose();
    _gradeController.dispose();
    _creditsController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Track Course'),
      content: SizedBox(
        width: 420,
        child: Form(
          key: _formKey,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextFormField(
                  controller: _courseCodeController,
                  decoration: const InputDecoration(
                    labelText: 'Course code',
                    hintText: 'CPTR 151',
                  ),
                  validator: (value) {
                    if (value == null || value.trim().isEmpty) {
                      return 'Enter a course code';
                    }
                    return null;
                  },
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _titleController,
                  decoration: const InputDecoration(
                    labelText: 'Title (optional)',
                  ),
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  initialValue: _status,
                  decoration: const InputDecoration(labelText: 'Status'),
                  items: const [
                    DropdownMenuItem(value: 'completed', child: Text('Completed')),
                    DropdownMenuItem(value: 'in_progress', child: Text('In progress')),
                    DropdownMenuItem(value: 'planned', child: Text('Planned')),
                    DropdownMenuItem(value: 'transfer', child: Text('Transfer')),
                    DropdownMenuItem(value: 'waived', child: Text('Waived')),
                  ],
                  onChanged: (value) {
                    if (value == null) return;
                    setState(() {
                      _status = value;
                    });
                  },
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _creditsController,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(labelText: 'Credits'),
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _termController,
                  decoration: const InputDecoration(
                    labelText: 'Term (optional)',
                    hintText: 'Spring 2026',
                  ),
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _gradeController,
                  decoration: const InputDecoration(
                    labelText: 'Grade (optional)',
                    hintText: 'A-',
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: () {
            if (!_formKey.currentState!.validate()) return;
            Navigator.pop(
              context,
              _AddCourseFormData(
                courseCode: _courseCodeController.text.trim(),
                title: _titleController.text.trim(),
                status: _status,
                credits: int.tryParse(_creditsController.text.trim()),
                term: _termController.text.trim(),
                grade: _gradeController.text.trim(),
              ),
            );
          },
          child: const Text('Save'),
        ),
      ],
    );
  }
}

class _AddCourseFormData {
  final String courseCode;
  final String title;
  final String status;
  final int? credits;
  final String term;
  final String grade;

  const _AddCourseFormData({
    required this.courseCode,
    required this.title,
    required this.status,
    required this.credits,
    required this.term,
    required this.grade,
  });
}
