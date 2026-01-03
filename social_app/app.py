from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'  # 建议替换成随机字符串
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///social.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# 登录管理器初始化
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


# -------------------------- 新增数据库模型（点赞/评论） --------------------------
# 用户模型（原有）
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    # 关联用户发布的动态
    posts = db.relationship('Post', backref='author', lazy=True)


# 动态模型（原有+新增点赞数字段）
class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    date_posted = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # 新增：点赞数
    likes = db.Column(db.Integer, default=0)
    # 关联动态的评论
    comments = db.relationship('Comment', backref='post', lazy=True, cascade="all, delete-orphan")


# 新增：点赞记录模型（避免重复点赞）
class Like(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    # 联合唯一索引：一个用户只能给一条动态点一次赞
    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='unique_user_post_like'),)


# 新增：评论模型
class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    date_posted = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    # 关联评论作者
    author = db.relationship('User', backref='comments')


# -------------------------- 原有路由（略作修改） --------------------------
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# 注册（原有）
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        if User.query.filter_by(username=username).first():
            flash('用户名已存在')
            return redirect(url_for('register'))
        if User.query.filter_by(email=email).first():
            flash('邮箱已存在')
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(username=username, email=email, password_hash=hashed_password)
        db.session.add(new_user)
        db.session.commit()

        flash('注册成功，请登录')
        return redirect(url_for('login'))
    return render_template('register.html')


# 登录（原有）
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()

        if not user or not check_password_hash(user.password_hash, password):
            flash('用户名或密码错误')
            return redirect(url_for('login'))

        login_user(user)
        return redirect(url_for('index'))
    return render_template('login.html')


# 登出（原有）
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# 首页（修改：显示点赞/评论，支持点赞/评论提交）
@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    # 发布新动态（原有）
    if request.method == 'POST' and 'content' in request.form:
        post_content = request.form['content']
        new_post = Post(content=post_content, author=current_user)
        db.session.add(new_post)
        db.session.commit()
        return redirect(url_for('index'))

    # 查询所有动态（按时间倒序）
    posts = Post.query.order_by(Post.date_posted.desc()).all()
    # 查询当前用户的点赞记录（用于前端显示“已点赞”状态）
    user_likes = [like.post_id for like in Like.query.filter_by(user_id=current_user.id).all()]

    return render_template('index.html', posts=posts, user_likes=user_likes)


# 发布动态（原有，可保留）
@app.route('/post', methods=['POST'])
@login_required
def post():
    return redirect(url_for('index'))


# -------------------------- 新增功能路由 --------------------------
# 1. 动态点赞/取消点赞
@app.route('/like/<int:post_id>')
@login_required
def like_post(post_id):
    post = Post.query.get_or_404(post_id)
    # 检查是否已点赞
    existing_like = Like.query.filter_by(user_id=current_user.id, post_id=post_id).first()

    if existing_like:
        # 取消点赞
        db.session.delete(existing_like)
        post.likes -= 1
    else:
        # 新增点赞
        new_like = Like(user_id=current_user.id, post_id=post_id)
        db.session.add(new_like)
        post.likes += 1

    db.session.commit()
    return redirect(url_for('index'))


# 2. 发布评论
@app.route('/comment/<int:post_id>', methods=['POST'])
@login_required
def add_comment(post_id):
    if request.method == 'POST':
        comment_content = request.form['comment_content']
        if comment_content.strip():  # 避免空评论
            new_comment = Comment(
                content=comment_content,
                author=current_user,
                post_id=post_id
            )
            db.session.add(new_comment)
            db.session.commit()
    return redirect(url_for('index'))


# 3. 删除自己的动态
@app.route('/delete/<int:post_id>')
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    # 仅允许作者删除
    if post.author.id != current_user.id:
        flash('你没有权限删除这条动态')
        return redirect(url_for('index'))

    db.session.delete(post)
    db.session.commit()
    return redirect(url_for('index'))


# 4. 个人主页（查看自己的动态）
@app.route('/profile')
@login_required
def profile():
    # 查询当前用户的所有动态（按时间倒序）
    user_posts = Post.query.filter_by(author=current_user).order_by(Post.date_posted.desc()).all()
    # 查询当前用户的点赞记录
    user_likes = [like.post_id for like in Like.query.filter_by(user_id=current_user.id).all()]
    return render_template('profile.html', posts=user_posts, user_likes=user_likes)


# 初始化数据库（首次运行需执行）
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)