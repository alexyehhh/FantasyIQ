import MatchupPlaceholder from "@/components/home/MatchupPlaceholder";
import NewsList from "@/components/home/NewsList";
import ScoresStrip from "@/components/home/ScoresStrip";
import StartSitBox from "@/components/home/StartSitBox";
import TopScorersList from "@/components/home/TopScorersList";

export default function HomePage() {
  return (
    <main className="home-grid min-h-[calc(100vh-56px)] w-full">
      <div className="border-b border-line px-4 py-6 sm:px-8 lg:border-b lg:border-r lg:[grid-area:matchups]">
        <MatchupPlaceholder />
      </div>
      <div className="border-b border-line px-4 py-6 sm:px-8 lg:[grid-area:topscorers]">
        <TopScorersList />
      </div>
      <div className="border-b border-line px-4 py-6 sm:px-8 lg:[grid-area:scores]">
        <ScoresStrip />
      </div>
      <div className="border-b border-line px-4 py-6 sm:px-8 lg:border-b-0 lg:border-r lg:[grid-area:startsit]">
        <StartSitBox />
      </div>
      <div className="px-4 py-6 sm:px-8 lg:[grid-area:news]">
        <NewsList />
      </div>
    </main>
  );
}
